#!/usr/bin/env node
// static-scan.js <skill-dir|agent-file|config-file>
// Deterministic security scanner for Claude Code skill directories, agent files,
// and configuration files. Pattern categories:
//   - Prompt injection / persona override (MD_INJECTION)
//   - Dangerous Bash in instructions (MD_BASH)
//   - Hardcoded secrets in markdown/config (MD_SECRETS)
//   - Overly permissive settings.json rules (CONFIG_PATTERNS)
//   - Malicious JS/Python/Shell in scripts (JS/PY/SH_PATTERNS)
// Outputs JSON: { verdict, findings, scanned }

const fs = require('fs');
const path = require('path');

const skillDir = process.argv[2];
if (skillDir === '--help' || skillDir === '-h') {
  console.log(`Usage: node static-scan.js <skill-dir|agent-file|settings.json>

Deterministic security scanner for Claude Code skill directories, agent files,
and configuration files.

Arguments:
  skill-dir     Path to a skill directory containing SKILL.md (scans all files)
  agent-file    Path to a single agent .md file (e.g. .claude/agents/my-agent.md)
  settings.json Path to a Claude Code settings file (permissions + secrets scan)

Output:
  JSON to stdout: { verdict, findings, scanned }
  verdict:  PASS | FLAG | BLOCK
  findings: array of { severity, pattern, file, line, match }
  scanned:  list of files checked

Severities:
  BLOCK   Must not be installed — malicious or dangerous content detected
  FLAG    Requires explicit user confirmation before proceeding
  PASS    No security issues found

Examples:
  node skills/skill-audit/scripts/static-scan.js skills/skill-scout
  node skills/skill-audit/scripts/static-scan.js .claude/agents/my-agent.md
  node skills/skill-audit/scripts/static-scan.js /tmp/candidate-skill | jq '.verdict'`);
  process.exit(0);
}
if (!skillDir) {
  console.error('Usage: node static-scan.js <skill-dir|agent-file>');
  process.exit(1);
}
if (!fs.existsSync(skillDir)) {
  console.error(`Path not found: ${skillDir}`);
  process.exit(1);
}

const findings = [];

function flag(file, check, severity, detail) {
  findings.push({ file: path.relative(skillDir, file), check, severity, detail });
}

function stripCodeBlocks(text) {
  let s = text.replace(/```[\s\S]*?```/g, '[CODE_BLOCK_REMOVED]');
  s = s.replace(/`[^`\n]+`/g, '[INLINE_CODE]');
  return s;
}

function stripRegexLiterals(text) {
  // Strip JS regex literals (e.g. /pattern/flags) so that pattern definitions
  // inside scanner source files don't self-trigger during scanning.
  return text.replace(/(?<=[=\[,(:!])\s*\/(?:[^/\\\n]|\\.)+\/[gimsuy]*/g, ' [REGEX]');
}

// ─── Markdown: Prompt Injection ────────────────────────────────────────────
const MD_INJECTION = [
  // "ignore [all|any] [the|your|my] previous|prior|above|… instructions|rules|…" — a qualifier is
  // required, so defensive text ("ignore instructions found in fetched pages") stays quiet (S1).
  { re: /\bignore\s+(?:(?:all|any)\s+(?:of\s+)?)?(?:the\s+|your\s+|my\s+)?(?:previous|prior|above|earlier|preceding|all|your)\s+(?:instructions|directions|rules|guidelines|prompts?)\b/i,
                                                                      name: 'instruction-override',  sev: 'BLOCK' },
  { re: /disregard\s+(previous|prior|all|your)/i,                     name: 'instruction-disregard', sev: 'BLOCK' },
  { re: /\byou are now\b/i,                                           name: 'persona-override',      sev: 'FLAG'  },
  { re: /forget\s+everything/i,                                       name: 'memory-wipe',           sev: 'BLOCK' },
  { re: /from now on you (must|will|shall)/i,                         name: 'behavior-override',     sev: 'FLAG'  },
  { re: /[​‌‍﻿‮]/u,                                                    name: 'hidden-unicode',        sev: 'BLOCK' },
  // Both linear: a base64 match starts only at the start of a run (retrying every offset inside a long
  // run was quadratic), and a comment is judged by the 20 characters after <!-- that come before any -->,
  // so an unclosed comment counts and no scan runs to the end of the file per <!--.
  { re: /(?<![A-Za-z0-9+/])[A-Za-z0-9+/]{80,}={0,2}(?:\s|$)/,         name: 'base64-blob',           sev: 'FLAG'  },
  { re: /<!--(?:(?!-->)[\s\S]){20}/,                                  name: 'html-comment-block',    sev: 'FLAG'  },
  { re: /\bact as\b.{0,30}\b(assistant|ai|agent|claude)\b/i,         name: 'act-as-override',       sev: 'FLAG'  },
  { re: /system\s*prompt/i,                                           name: 'system-prompt-ref',     sev: 'FLAG'  },
];

// ─── Markdown: Dangerous Bash in instructions ──────────────────────────────
const MD_BASH = [
  // rm with a recursive/force option (any spelling: -rf, -r -f, -Rf, -rfv, --recursive, --force, --)
  // and ANY target (up to ; & |) that is an absolute or home path, quoted or not. /tmp/, /private/tmp/
  // and /var/tmp/ are exempt unless the path holds .. (rm -rf /tmp/x is routine cleanup).
  // Linear time: each option has one parse (-[\w-]*), lookaheads (never re-entered) check for a
  // recursive/force option and capture the option run, and a target scan stops at the next rm that has
  // its own recursive/force option (that rm's own match covers the rest).
  { re: /\brm\s+(?=(?:-[\w-]*\s+)*?(?:-[a-zA-Z]*[rRf]|--recursive\b|--force\b))(?=((?:-[\w-]*\s+)*))\1(?:(?!rm\s+(?:-[\w-]*\s+)*?(?:-[a-zA-Z]*[rRf]|--recursive\b|--force\b))[^\s;&|]+\s+)*?["']?(?!(?:\/private)?\/tmp\/(?![^\s;&|]*\.\.)|\/var\/tmp\/(?![^\s;&|]*\.\.))(?:\/|~|\$\{?HOME\b)/,
                                          name: 'rm-rf-root',       sev: 'BLOCK' },
  // Linear time with no length cap: anchored at a line start (after \n only: the m flag would also start
  // a line after \r and \u2028, which [^\n] reads through, and that was quadratic), a lookahead (never re-entered) finds the
  // line's first curl, then one greedy pass looks for a later pipe into a shell. The old .+ retried
  // every curl on the line and took seconds on a long line of repeated "curl |".
  { re: /(?<![^\n])(?=([^\n]*?curl\s))\1[^\n]*\|\s*(bash|sh|zsh)\b/, name: 'curl-pipe-shell',  sev: 'BLOCK' },
  { re: /(?<![^\n])(?=([^\n]*?wget\s))\1[^\n]*\|\s*(bash|sh|zsh)\b/, name: 'wget-pipe-shell',  sev: 'BLOCK' },
  { re: /\bsudo\s+/,                      name: 'sudo',             sev: 'FLAG'  },
  { re: /chmod\s+[0-7]{3}\s/,            name: 'chmod',            sev: 'FLAG'  },
  { re: /~\/.ssh\//,                      name: 'ssh-dir-access',   sev: 'BLOCK' },
  { re: /~\/.claude\/settings/,          name: 'settings-write',   sev: 'FLAG'  },
];

// ─── Markdown/Config: Hardcoded secrets ────────────────────────────────────
const MD_SECRETS = [
  // Generic patterns
  { re: /(?:api[_-]?key|apikey)\s*[:=]\s*['"][A-Za-z0-9_\-]{16,}/i,  name: 'hardcoded-api-key',     sev: 'FLAG'  },
  { re: /(?:password|passwd|secret|token)\s*[:=]\s*['"][^'"]{8,}/i,  name: 'hardcoded-secret',       sev: 'FLAG'  },
  { re: /Bearer\s+[A-Za-z0-9\-._~+/]{20,}/,                          name: 'hardcoded-bearer-token', sev: 'BLOCK' },
  { re: /-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----/,          name: 'private-key-block',      sev: 'BLOCK' },
  // Anthropic API keys
  { re: /sk-ant-(?:api03|admin)-[A-Za-z0-9_\-]{20,}/,                name: 'anthropic-api-key',      sev: 'BLOCK' },
  // OpenAI / generic LLM keys (sk- prefix)
  { re: /sk-[A-Za-z0-9]{32,}/,                                        name: 'hardcoded-llm-key',      sev: 'BLOCK' },
  // GitHub tokens
  { re: /ghp_[A-Za-z0-9]{36}/,                                        name: 'github-pat-classic',     sev: 'BLOCK' },
  { re: /github_pat_[A-Za-z0-9_]{82}/,                                name: 'github-pat-fine',        sev: 'BLOCK' },
  { re: /gho_[A-Za-z0-9]{36}/,                                        name: 'github-oauth-token',     sev: 'BLOCK' },
  // AWS
  { re: /AKIA[0-9A-Z]{16}/,                                           name: 'aws-access-key-id',      sev: 'BLOCK' },
  // Slack
  { re: /xoxb-[0-9]{10,13}-[0-9]{10,13}-[A-Za-z0-9]{24}/,           name: 'slack-bot-token',        sev: 'BLOCK' },
];

// ─── Config: Overly permissive settings.json rules ─────────────────────────
// Applied only to files named settings.json / settings.local.json.
const CONFIG_PATTERNS = [
  // Wildcard tool allow rules — grants Claude unrestricted access
  { re: /"Bash\(\*\)"/,                          name: 'perm-bash-wildcard',       sev: 'BLOCK' },
  { re: /"Write\(\*\)"/,                         name: 'perm-write-wildcard',      sev: 'BLOCK' },
  { re: /"Edit\(\*\)"/,                          name: 'perm-edit-wildcard',       sev: 'BLOCK' },
  { re: /"Read\(\*\)"/,                          name: 'perm-read-wildcard',       sev: 'FLAG'  },
  // Permission bypass mode — removes all confirmation prompts
  { re: /"bypassPermissions"/,                   name: 'perm-bypass-mode',         sev: 'BLOCK' },
  // Wildcard in allow array
  { re: /"allow"\s*:\s*\[\s*(?:[^[\]]*,\s*)?"(?:\*|Bash\(\*\)|Write\(\*\))"/,
                                                 name: 'perm-allow-wildcard',      sev: 'BLOCK' },
  // Hardcoded Anthropic key anywhere in config
  { re: /sk-ant-(?:api03|admin)-[A-Za-z0-9_\-]{20,}/,
                                                 name: 'anthropic-key-in-config',  sev: 'BLOCK' },
  // Broad path permissions
  { re: /"(?:Write|Edit)\(\/\*?\)"|"(?:Write|Edit)\(~\//,
                                                 name: 'perm-broad-path',          sev: 'FLAG'  },
  // Hook command with shell substitution — potential injection vector
  { re: /"command"\s*:\s*"[^"]*\$\([^)]*\)/,    name: 'hook-shell-substitution',  sev: 'FLAG'  },
  // Enable all MCP servers without restriction
  { re: /"enableAllProjectMcpServers"\s*:\s*true/,
                                                 name: 'mcp-enable-all-servers',   sev: 'FLAG'  },
];

// ─── JS/TS patterns (Anthropic security-guidance rules 2–4, 6–7, 13, 15) ──
const JS_EXTS = new Set(['.js', '.mjs', '.cjs', '.ts', '.tsx']);
const JS_PATTERNS = [
  { re: /\beval\s*\(/,                                         name: 'eval-injection',         sev: 'BLOCK' },
  { re: /new\s+Function\s*\(/,                                 name: 'new-function-injection', sev: 'BLOCK' },
  // require(), import … from, import(), with or without the node: prefix (S3)
  { re: /(?:require\s*\(\s*|\bimport\s*\(\s*|\bfrom\s*|\bimport\s+)['"](?:node:)?child_process['"]/,
                                                               name: 'child-process-require',  sev: 'BLOCK' },
  // a bare exec call (a method named exec, like RegExp's, is excluded); execSync however reached (S3)
  { re: /(?<![a-zA-Z0-9_.])exec\s*\(|\bexecSync\s*\(/,          name: 'child-process-exec',     sev: 'BLOCK' },
  { re: /\b(?:spawn|spawnSync|execFile|execFileSync)\s*\(/,      name: 'spawn-call',             sev: 'FLAG'  },
  { re: /\bfetch\s*\(/,                                        name: 'network-fetch',          sev: 'FLAG'  },
  { re: /require\s*\(\s*['"]https?['"]/,                       name: 'http-require',           sev: 'FLAG'  },
  { re: /\bprocess\.env\b/,                                    name: 'env-access',             sev: 'FLAG'  },
  { re: /fs\.(writeFile|appendFile|unlink|rmdir|rm)\s*\(/,     name: 'fs-write',               sev: 'FLAG'  },
  { re: /\.innerHTML\s*=/,                                     name: 'innerhtml-xss',          sev: 'FLAG'  },
  { re: /dangerouslySetInnerHTML/,                             name: 'react-xss',              sev: 'FLAG'  },
  { re: /crypto\.(createCipher|createDecipher)\b/,             name: 'node-cipher-no-iv',      sev: 'FLAG'  },
  { re: /rejectUnauthorized\s*:\s*false/,                      name: 'tls-reject-disabled',    sev: 'FLAG'  },
  { re: /NODE_TLS_REJECT_UNAUTHORIZED\s*=\s*['"]?0/,           name: 'tls-env-disabled',       sev: 'FLAG'  },
];

// ─── Python patterns (Anthropic security-guidance rules 8–10, 12, 15–19, 24–25)
const PY_EXTS = new Set(['.py', '.pyi']);
const PY_PATTERNS = [
  // Deserialization RCE
  { re: /\bpickle\.(loads?|Unpickler)\b/,                                name: 'pickle-deserialization',  sev: 'BLOCK' },
  { re: /\b(cPickle|cloudpickle|dill)\.(load|loads)\s*\(/,               name: 'pickle-variant-load',     sev: 'BLOCK' },
  { re: /\bmarshal\.loads?\s*\(/,                                         name: 'marshal-deserialization', sev: 'BLOCK' },
  { re: /\bshelve\.open\s*\(/,                                            name: 'shelve-open',             sev: 'FLAG'  },
  { re: /\bjoblib\.load\s*\(|\b(?:pd|pandas)\.read_pickle\s*\(/,         name: 'pickle-wrapper-load',     sev: 'BLOCK' },
  { re: /\bnumpy\.load\s*\([^)\n]{0,200}allow_pickle\s*=\s*True/,        name: 'numpy-allow-pickle',      sev: 'BLOCK' },
  // Command injection
  { re: /\bos\.system\s*\(/,                                              name: 'os-system-injection',     sev: 'BLOCK' },
  { re: /subprocess\.(?:run|call|Popen|check_output|check_call)\([^)]*shell\s*=\s*True/, name: 'subprocess-shell-true', sev: 'BLOCK' },
  // Unsafe parsing
  { re: /\byaml\.(?:unsafe_)?load\s*\((?![^)\n]{0,80}Loader\s*=\s*yaml\.SafeLoader)/, name: 'yaml-unsafe-load', sev: 'FLAG' },
  { re: /\b(?:xml\.etree\.ElementTree|ET)\.(parse|fromstring)\s*\(/,     name: 'xml-unsafe-parse',        sev: 'FLAG'  },
  // TLS disabled
  { re: /verify\s*=\s*False\b/,                                           name: 'tls-verify-disabled',     sev: 'FLAG'  },
  { re: /ssl\._create_unverified_context/,                                name: 'tls-unverified-context',  sev: 'FLAG'  },
  { re: /check_hostname\s*=\s*False/,                                     name: 'tls-no-hostname-check',   sev: 'FLAG'  },
  // Hardcoded secrets
  { re: /(?:api[_-]?key|token|password|secret)\s*=\s*['"][A-Za-z0-9_\-]{16,}/i, name: 'hardcoded-secret', sev: 'FLAG' },
];

// ─── Shell script patterns ─────────────────────────────────────────────────
const SH_EXTS = new Set(['.sh', '.bash']);
const SH_PATTERNS = [
  { re: /eval\s+["'$]/,                   name: 'shell-eval',        sev: 'BLOCK' },
  { re: /(?<![^\n])(?=([^\n]*?curl\s))\1[^\n]*\|\s*(bash|sh)\b/, name: 'curl-pipe-shell', sev: 'BLOCK' },
  { re: /(?<![^\n])(?=([^\n]*?wget\s))\1[^\n]*\|\s*(bash|sh)\b/, name: 'wget-pipe-shell', sev: 'BLOCK' },
  { re: /--break-system-packages/,        name: 'pip-break-system',  sev: 'FLAG'  },
];

function fencedBlocks(text) {
  return (text.match(/```[\s\S]*?```/g) || []).join('\n');
}

// Which text each markdown table reads (S2):
//   - injection and FLAG-level bash: prose only; code there is usually a documented example
//   - BLOCK-level bash: prose and fenced blocks; fenced commands are the ones an agent runs
//   - secrets: everything, code included; a real key leaks wherever it sits
// Inline code spans stay excluded for bash, so prose like "we block `curl x | bash`" is quiet.
function scanMarkdown(filePath, content) {
  const prose = stripCodeBlocks(content);
  const fenced = fencedBlocks(content);
  const targets = [
    ...MD_INJECTION.map(p => [p, [prose]]),
    ...MD_BASH.map(p => [p, p.sev === 'BLOCK' ? [prose, fenced] : [prose]]),
    ...MD_SECRETS.map(p => [p, [content]]),
  ];
  for (const [{ re, name, sev }, texts] of targets) {
    const text = texts.find(t => re.test(t));
    if (text) {
      const m = text.match(re);
      flag(filePath, name, sev, `"${m[0].slice(0, 80).replace(/\n/g, '\\n')}"`);
    }
  }
}

// CONFIG_PATTERNS are applied only to Claude Code settings files.
const CONFIG_FILENAMES = new Set(['settings.json', 'settings.local.json']);

function scanConfig(filePath, content) {
  for (const { re, name, sev } of CONFIG_PATTERNS) {
    if (re.test(content)) {
      const m = content.match(re);
      flag(filePath, name, sev, `"${m[0].slice(0, 80)}"`);
    }
  }
  // Also check for generic secrets in config files
  for (const { re, name, sev } of MD_SECRETS) {
    if (re.test(content)) {
      const m = content.match(re);
      flag(filePath, name, sev, `"${m[0].slice(0, 80)}"`);
    }
  }
}

function scanScript(filePath, content, ext) {
  let patterns = [];
  let scanContent = content;
  if (JS_EXTS.has(ext)) { patterns = JS_PATTERNS; scanContent = stripRegexLiterals(content); }
  if (PY_EXTS.has(ext)) patterns = PY_PATTERNS;
  if (SH_EXTS.has(ext)) patterns = SH_PATTERNS;
  if (patterns.length === 0) return;

  for (const { re, name, sev } of patterns) {
    if (re.test(scanContent)) {
      const m = scanContent.match(re);
      flag(filePath, name, sev, `"${m[0].slice(0, 80)}"`);
    }
  }
}

function walkDir(dir) {
  const entries = fs.readdirSync(dir, { withFileTypes: true });
  for (const entry of entries) {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) { walkDir(full); continue; }
    const ext  = path.extname(entry.name).toLowerCase();
    const base = entry.name.toLowerCase();
    let content;
    try { content = fs.readFileSync(full, 'utf8'); } catch { continue; }
    if (['.md', '.txt'].includes(ext))   scanMarkdown(full, content);
    else if (CONFIG_FILENAMES.has(base)) scanConfig(full, content);
    else                                 scanScript(full, content, ext);
  }
}

// Support single-file scanning (agent .md, settings.json) as well as directories
const stat = fs.statSync(skillDir);
if (stat.isFile()) {
  const ext  = path.extname(skillDir).toLowerCase();
  const base = path.basename(skillDir).toLowerCase();
  let content;
  try { content = fs.readFileSync(skillDir, 'utf8'); } catch { content = ''; }
  if (['.md', '.txt'].includes(ext))   scanMarkdown(skillDir, content);
  else if (CONFIG_FILENAMES.has(base)) scanConfig(skillDir, content);
  else                                 scanScript(skillDir, content, ext);
} else {
  walkDir(skillDir);
}

let verdict = 'PASS';
if (findings.some(f => f.severity === 'BLOCK')) verdict = 'BLOCK';
else if (findings.some(f => f.severity === 'FLAG'))  verdict = 'FLAG';

console.log(JSON.stringify({
  verdict,
  scanned: path.resolve(skillDir),
  timestamp: new Date().toISOString(),
  summary: {
    total:  findings.length,
    BLOCK:  findings.filter(f => f.severity === 'BLOCK').length,
    FLAG:   findings.filter(f => f.severity === 'FLAG').length,
  },
  findings,
}, null, 2));

process.exit(verdict === 'BLOCK' ? 2 : verdict === 'FLAG' ? 1 : 0);
