#!/usr/bin/env node
// validate-skills.js
// Validates SKILL.md frontmatter across all skills in the skills/ directory.
// Exits 0 if all pass, 1 if any fail.

const fs   = require('fs');
const path = require('path');

if (process.argv[2] === '--help' || process.argv[2] === '-h') {
  console.log(`Usage: node scripts/validate-skills.js [skills-dir]

Validate SKILL.md frontmatter for all skills.

Arguments:
  skills-dir   Path to skills directory (default: ./skills)

Checks:
  - name field present and ≤ 64 chars (Agent Skills spec)
  - description field present and ≤ 1024 chars (Agent Skills spec)
  - compatibility field present
  - description contains "Use when" trigger clause
  - No description starts with raw quotes (parsing artifact)
  - Every invocation-shaped skill/agent reference resolves (skills/*/**.md,
    .claude/agents/*.md): a backticked kebab name after invoke/run/use/
    recommend/dispatch/..., or followed by "skill"/"agent". Namespaced plugin
    skills (ns:name) must be declared in EXTERNAL_SKILLS.

Exit codes:
  0  All skills pass
  1  One or more skills fail`);
  process.exit(0);
}

// Plugin skills this repo's skills route to. CI cannot see installed plugins, so
// each namespaced reference must be declared here — a deliberate, reviewable list.
// They are OPTIONAL: install.sh installs no plugin, and target projects (and the
// Hermes box) may not have them. So every reference must state its fallback on
// the same or the next two lines ("if ... installed/available", or "otherwise").
const EXTERNAL_SKILLS = [
  'superpowers:writing-skills', // D1 (2026-10-14): preferred build-from-scratch tool, with a fallback
];
const FALLBACK_RE = /\botherwise\b|\bif\b[^.\n]{0,80}\b(?:installed|available)\b/i;

// A backticked kebab name (optionally ns:name) right after an invocation verb,
// or followed by "skill"/"agent". Plain backticked file names and flags don't match.
// Deliberately narrow (precision over recall): other phrasings — unquoted names,
// single-word names, verbs not listed — are not checked. "with" is excluded on
// purpose: "with `dry-run` mode" is prose, not a reference.
const REF_RE = /\b(?:invoke|invoking|recommend|recommends|run|use|using|route to|hand off to|dispatch|dispatches|spawn|call|calls)\s+(?:the\s+)?`\/?((?:[a-z0-9-]+:)?[a-z0-9]+(?:-[a-z0-9]+)+)`|`\/?((?:[a-z0-9-]+:)?[a-z0-9]+(?:-[a-z0-9]+)+)`\s+(?:skill|agent|sub-agent|subagent)\b/gi;

// Generated eval reports and refine logs are history, not instructions. Per
// location: skill dirs hold SKILL-/AGENT-/TEAM-EVAL.md and *REFINE-LOG.md;
// .claude/agents/ holds <name>-EVAL.md and <name>-REFINE-LOG.md beside the
// definitions (those must not be counted as agents either).
const SKILL_DIR_HISTORY_RE = /^(?:SKILL|AGENT|TEAM)-EVAL\.md$|REFINE-LOG\.md$/;
const AGENT_DIR_HISTORY_RE = /-EVAL\.md$|-REFINE-LOG\.md$/;

function listDirs(dir) {
  if (!fs.existsSync(dir)) return [];
  return fs.readdirSync(dir, { withFileTypes: true }).filter(e => e.isDirectory()).map(e => e.name);
}

function walkMarkdown(dir) {
  if (!fs.existsSync(dir)) return [];
  return fs.readdirSync(dir, { withFileTypes: true }).flatMap(e => {
    const p = path.join(dir, e.name);
    if (e.isDirectory()) return walkMarkdown(p);
    return e.name.endsWith('.md') && !SKILL_DIR_HISTORY_RE.test(e.name) ? [p] : [];
  });
}

// Returns [{ name, location, reason }] for every invocation-shaped reference that
// names neither a skill (skillsDir, knownSkillDirs), an agent (agentDirs), nor a
// declared external plugin skill (reason 'unresolved'), and for every declared
// external reference with no stated fallback nearby (reason 'no-fallback').
function findUnresolvedSkillRefs({ skillsDir, agentDirs = [], knownSkillDirs = [], external = EXTERNAL_SKILLS }) {
  const known = new Set([...listDirs(skillsDir), ...knownSkillDirs.flatMap(listDirs)]);
  const agentFiles = agentDirs.flatMap(d => (fs.existsSync(d) ? fs.readdirSync(d) : [])
    .filter(f => f.endsWith('.md') && !AGENT_DIR_HISTORY_RE.test(f)).map(f => path.join(d, f)));
  for (const f of agentFiles) known.add(path.basename(f, '.md'));
  const declared = new Set(external);

  const unresolved = [];
  const scanned = [skillsDir, ...knownSkillDirs].flatMap(walkMarkdown);
  for (const file of [...scanned, ...agentFiles]) {
    const text = fs.readFileSync(file, 'utf8');
    for (const m of text.matchAll(REF_RE)) {
      const name = m[1] || m[2];
      if (!/^[a-z0-9:-]+$/.test(name)) continue; // /i matches verbs; names stay lowercase kebab
      const line = text.slice(0, m.index).split('\n').length;
      const location = `${path.relative(process.cwd(), file)}:${line}`;
      if (name.includes(':') && declared.has(name)) {
        const near = text.split('\n').slice(line - 1, line + 2).join('\n');
        if (!FALLBACK_RE.test(near)) unresolved.push({ name, location, reason: 'no-fallback' });
        continue;
      }
      if (known.has(name)) continue;
      unresolved.push({ name, location, reason: 'unresolved' });
    }
  }
  return unresolved;
}

module.exports = { findUnresolvedSkillRefs, EXTERNAL_SKILLS };
if (require.main !== module) return;

const skillsDir = process.argv[2] || path.join(process.cwd(), 'skills');
const skills = fs.readdirSync(skillsDir, { withFileTypes: true })
  .filter(e => e.isDirectory())
  .map(e => e.name)
  .sort();

let passed = 0;
let failed = 0;

for (const skill of skills) {
  const skillFile = path.join(skillsDir, skill, 'SKILL.md');
  if (!fs.existsSync(skillFile)) {
    console.log(`  FAIL  ${skill}: SKILL.md not found`);
    failed++;
    continue;
  }

  const content = fs.readFileSync(skillFile, 'utf8');

  // Extract frontmatter between --- delimiters
  const fmMatch = content.match(/^---\n([\s\S]+?)\n---/);
  if (!fmMatch) {
    console.log(`  FAIL  ${skill}: no YAML frontmatter found`);
    failed++;
    continue;
  }
  const fm = fmMatch[1];

  const errors = [];

  // name
  const nameMatch = fm.match(/^name:\s*(.+)/m);
  if (!nameMatch) {
    errors.push('missing name field');
  } else {
    const name = nameMatch[1].trim().replace(/^["']|["']$/g, '');
    if (name.length > 64) errors.push(`name too long (${name.length} chars, max 64)`);
    if (/[A-Z]/.test(name)) errors.push('name must be lowercase');
    if (/[^a-z0-9-]/.test(name)) errors.push('name must use only lowercase letters, numbers, hyphens');
  }

  // description
  const descMatch = fm.match(/^description:\s*(.+)/m);
  if (!descMatch) {
    errors.push('missing description field');
  } else {
    const desc = descMatch[1].trim().replace(/^["']|["']$/g, '');
    if (desc.length > 1024) errors.push(`description too long (${desc.length} chars, max 1024)`);
    if (desc.length < 20)   errors.push(`description too short (${desc.length} chars)`);
    if (!/[Uu]se when/i.test(desc)) errors.push('description missing "Use when" trigger clause');
    // A stray quote is one that remains AFTER stripping outer YAML delimiters
    if (/^["']/.test(desc)) errors.push('description starts with stray quote after YAML parsing (artifact)');
  }

  // compatibility
  if (!/^compatibility:/m.test(fm)) {
    errors.push('missing compatibility field (Agent Skills spec requirement)');
  }

  if (errors.length === 0) {
    console.log(`  PASS  ${skill}`);
    passed++;
  } else {
    errors.forEach(e => console.log(`  FAIL  ${skill}: ${e}`));
    failed++;
  }
}

console.log(`\n${passed + failed} skills checked — ${passed} passed, ${failed} failed`);

const repoRoot = path.resolve(skillsDir, '..');
const unresolved = findUnresolvedSkillRefs({
  skillsDir,
  agentDirs: [path.join(repoRoot, '.claude', 'agents')],
  knownSkillDirs: [path.join(repoRoot, '.claude', 'skills')],
});
unresolved.forEach(r => console.log(r.reason === 'no-fallback'
  ? `  FAIL  optional plugin skill \`${r.name}\` referenced without a fallback at ${r.location}`
  : `  FAIL  unresolved skill reference \`${r.name}\` at ${r.location}`));
console.log(`skill references: ${unresolved.length} unresolved`);
process.exit(failed > 0 || unresolved.length > 0 ? 1 : 0);
