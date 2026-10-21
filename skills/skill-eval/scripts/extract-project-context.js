#!/usr/bin/env node
// extract-project-context.js [project-root]
// Reads common project files and extracts context for project-aware skill evaluation.
// Writes evals/project-context.json and emits JSON to stdout.

const fs   = require('fs');
const path = require('path');
const os   = require('os');

if (process.argv[2] === '--help' || process.argv[2] === '-h') {
  console.log(`Usage: node extract-project-context.js [project-root]

Extract project context for project-aware skill evaluation.

Arguments:
  project-root   Path to the project root (default: current directory)

Output:
  Writes evals/project-context.json and emits JSON to stdout.
  Extracted fields: project_name, stack, workflow_terms, installed_skills,
  key_phrases, artifact_paths, hooks, mcp_servers, plugins.

Sources read (if present):
  package.json, pyproject.toml, CLAUDE.md, README.md,
  .planning/REQUIREMENTS.md, .planning/CONTEXT.md, skills/ directory,
  .claude/settings.json (hooks), .mcp.json (MCP servers),
  ~/.claude/settings.json (plugins)

Examples:
  node skills/skill-eval/scripts/extract-project-context.js
  node skills/skill-eval/scripts/extract-project-context.js /path/to/project`);
  process.exit(0);
}
const projectRoot = process.argv[2] || process.cwd();

const context = {
  project_name:    path.basename(projectRoot),
  stack:           [],
  workflow_terms:  [],
  installed_skills:[],
  key_phrases:     [],
  artifact_paths:  [],
  hooks:           [],
  mcp_servers:     [],
  plugins:         [],
  audited_repos:   [],
  audit_signals:   { architecture_patterns: [], ref_stack_extended: [] },
};

function readFile(...parts) {
  try { return fs.readFileSync(path.join(...parts), 'utf8'); } catch { return null; }
}

// ── package.json ─────────────────────────────────────────────────────────────
const pkg = readFile(projectRoot, 'package.json');
if (pkg) {
  try {
    const p = JSON.parse(pkg);
    if (p.name)        context.project_name = p.name;
    if (p.description) context.key_phrases.push(p.description);
    const deps = Object.keys({ ...(p.dependencies || {}), ...(p.devDependencies || {}) });
    const stackMap = {
      next:       'Next.js',   react:      'React',     vue:      'Vue',
      svelte:     'Svelte',    angular:    'Angular',   express:  'Express',
      typescript: 'TypeScript',fastapi:    'FastAPI',   django:   'Django',
      flask:      'Flask',     rails:      'Rails',     laravel:  'Laravel',
    };
    for (const [dep, name] of Object.entries(stackMap)) {
      if (deps.some(d => d.toLowerCase().includes(dep))) context.stack.push(name);
    }
    // engines.node declares a Node.js runtime requirement — treat as a stack signal
    if (p.engines && p.engines.node) context.stack.push('Node.js');
  } catch {}
}

// ── pyproject.toml ───────────────────────────────────────────────────────────
const pyproject = readFile(projectRoot, 'pyproject.toml');
if (pyproject) {
  const m = pyproject.match(/^name\s*=\s*["'](.+)["']/m);
  if (m) context.project_name = m[1];
  if (pyproject.includes('fastapi')) context.stack.push('FastAPI');
  if (pyproject.includes('django'))  context.stack.push('Django');
}

// ── CLAUDE.md — workflow conventions and key terms ──────────────────────────
const claudeMd = readFile(projectRoot, 'CLAUDE.md') ||
                 readFile(projectRoot, '.claude', 'CLAUDE.md');
if (claudeMd) {
  // Capitalized acronyms/terms = project-specific vocabulary
  const caps = claudeMd.match(/\b[A-Z][A-Z_]{2,}\b/g) || [];
  context.workflow_terms.push(...[...new Set(caps)].filter(t => t.length < 20).slice(0, 15));
  // "Use X" patterns reveal preferred tooling and conventions
  for (const m of claudeMd.matchAll(/\buse\s+([A-Za-z][\w/-]+)/gi))
    context.key_phrases.push(m[1]);
  // File/directory paths mentioned
  for (const m of claudeMd.matchAll(/`([./][\w./\-]+)`/g))
    context.artifact_paths.push(m[1]);
}

// ── README.md — project description ─────────────────────────────────────────
const readme = readFile(projectRoot, 'README.md');
if (readme) {
  // First substantive line after the H1 title
  const m = readme.split('\n').slice(0, 30).join('\n').match(/^#{1,2}\s+.+\n+([^\n#]{10,})/m);
  if (m) context.key_phrases.push(m[1].trim());
}

// ── .planning/ and CONTEXT.md ─────────────────────────────────────────────
const planning = readFile(projectRoot, '.planning', 'REQUIREMENTS.md') ||
                 readFile(projectRoot, '.planning', 'intel', 'CONTEXT.md') ||
                 readFile(projectRoot, 'CONTEXT.md');
if (planning) {
  // Multi-word Title-Case phrases = domain terminology
  const terms = planning.match(/\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+)+/g) || [];
  context.key_phrases.push(...[...new Set(terms)].slice(0, 8));
  for (const m of planning.matchAll(/`([./][\w./\-]+)`/g))
    context.artifact_paths.push(m[1]);
}

// ── Installed skills ─────────────────────────────────────────────────────────
const skillsDir = path.join(projectRoot, 'skills');
if (fs.existsSync(skillsDir)) {
  context.installed_skills = fs.readdirSync(skillsDir, { withFileTypes: true })
    .filter(e => e.isDirectory())
    .map(e => e.name);
}

// ── Hooks (.claude/settings.json — project level, then global) ───────────────
function extractHooks(settingsRaw, into) {
  if (!settingsRaw) return;
  try {
    const settings = JSON.parse(settingsRaw);
    const hooksObj = settings.hooks || {};
    for (const [event, entries] of Object.entries(hooksObj)) {
      // A malformed list, entry or hook is skipped, so the rest of the file is still read (review G11, N4)
      for (const entry of (Array.isArray(entries) ? entries : [])) {
        if (!entry) continue;
        const matcher = entry.matcher || null;
        for (const h of (Array.isArray(entry.hooks) ? entry.hooks : [])) {
          if (h && h.command) {
            // Commands are like: `"<node-bin>" "<script.js>"` or `bash "<script.sh>"`
            // Find the last token ending with a known script extension
            const scriptRe = /["']?([^\s"']+\.(?:js|mjs|cjs|ts|sh|py|rb))["']?/gi;
            const matches = [...h.command.matchAll(scriptRe)];
            const cmd = matches.length
              ? path.basename(matches[matches.length - 1][1])
              : path.basename(h.command.split(' ')[0].replace(/["']/g, ''));
            into.push({ event, matcher, command: cmd });
          }
        }
      }
    }
  } catch {}
}
extractHooks(readFile(projectRoot, '.claude', 'settings.json'), context.hooks);
extractHooks(readFile(os.homedir(), '.claude', 'settings.json'), context.hooks);

// ── MCP servers (.mcp.json) ──────────────────────────────────────────────────
const mcpRaw = readFile(projectRoot, '.mcp.json');
if (mcpRaw) {
  try {
    const mcp = JSON.parse(mcpRaw);
    context.mcp_servers = Object.keys(mcp.mcpServers || {});
  } catch {}
}

// ── Plugins (~/.claude/settings.json:enabledPlugins) ─────────────────────────
const globalSettingsRaw = readFile(os.homedir(), '.claude', 'settings.json');
if (globalSettingsRaw) {
  try {
    const globalSettings = JSON.parse(globalSettingsRaw);
    const enabled = globalSettings.enabledPlugins || {};
    // Strip @marketplace-name suffix: "superpowers@claude-plugins-official" → "superpowers"
    context.plugins = Object.keys(enabled).map(k => k.split('@')[0]);
  } catch {}
}

// ── Deduplicate and trim ─────────────────────────────────────────────────────
context.stack           = [...new Set(context.stack)];
context.workflow_terms  = [...new Set(context.workflow_terms)];
context.artifact_paths  = [...new Set(context.artifact_paths)].slice(0, 10);
context.key_phrases     = [...new Set(context.key_phrases.filter(Boolean))].slice(0, 10);
context.hooks           = context.hooks.slice(0, 20);
context.mcp_servers     = [...new Set(context.mcp_servers)];
context.plugins         = [...new Set(context.plugins)];

// ── Write output ─────────────────────────────────────────────────────────────
const outDir  = path.join(projectRoot, 'evals');
const outPath = path.join(outDir, 'project-context.json');
fs.mkdirSync(outDir, { recursive: true });

// Preserve security fields written by project-audit — never overwrite them
try {
  const prior = JSON.parse(fs.readFileSync(outPath, 'utf8'));
  if (prior.security_grade)        context.security_grade        = prior.security_grade;
  if (prior.security_score !== undefined) context.security_score = prior.security_score;
  if (prior.security_last_scanned) context.security_last_scanned = prior.security_last_scanned;
  if (prior.audited_repos && prior.audited_repos.length) context.audited_repos = prior.audited_repos;
  if (prior.audit_signals) context.audit_signals = prior.audit_signals;
} catch { /* file doesn't exist yet — no prior security data to preserve */ }

fs.writeFileSync(outPath, JSON.stringify(context, null, 2));
console.error(`Project context written to ${outPath}`);
console.log(JSON.stringify(context, null, 2));
