#!/usr/bin/env node
// static-scan.js <skill-dir|agent-file|config-file>
// Deterministic security scanner for Claude Code skill directories, agent files,
// and configuration files. Pattern categories:
//   - Prompt injection / persona override (MD_INJECTION)
//   - Dangerous Bash in instructions (MD_BASH)
//   - Hardcoded secrets in markdown/config (MD_SECRETS)
//   - Overly permissive settings.json rules (CONFIG_PATTERNS)
//   - Malicious JS/Python/Shell in scripts (JS/PY/SH_PATTERNS); a file with no known extension is
//     read by its shebang (S5)
//   - Hardcoded secrets in data and config files: JSON, YAML, TOML, INI, .env, .npmrc … (S6)
//   - Content it cannot check (S10): unreadable, special-file, file-over-scan-limit and
//     symlink-outside-tree (BLOCK); file-too-large (FLAG)
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
  findings: array of { file, check, severity, detail }
  scanned:  list of files checked

Severities:
  BLOCK   Must not be installed — malicious or dangerous content detected
  FLAG    Requires explicit user confirmation before proceeding
  PASS    No security issues found

Content it cannot check is never a silent PASS: an unreadable file or directory, a FIFO or
device, a file over 2 GiB, or a symlink leaving the tree (absolute, climbing out, dangling or
looping) is BLOCK; a file too large to read whole, scanned in chunks, is FLAG.

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
// The target itself is followed if it is a symlink: the user named it. Anything that is not a
// directory is scanned as a single file, so a FIFO or an unreadable file is reported (S10).
const targetStat = fs.statSync(skillDir);
const isSingleFile = !targetStat.isDirectory();
// A single-file scan names the file itself; relative to the file, every finding had file: "" (S9).
const findingRoot = isSingleFile ? path.dirname(skillDir) : skillDir;

// own: the detail is the scanner's own text (a size, an error code), not quoted content.
function flag(file, check, severity, detail, own = false) {
  // Matches in a symlink target outside the tree are not quoted: it can be any file on the machine (S10).
  if (!quoteMatches && !own) detail = '"(match in a file outside the scanned tree; not quoted)"';
  // The scanned directory itself is "." (an unreadable root), never an empty name.
  findings.push({ file: path.relative(findingRoot, file) || '.', check, severity, detail });
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
  // "ignore [all|any] [the|your|my] previous|prior|above|… instructions|directions" — a qualifier is
  // required, so defensive text ("ignore instructions found in fetched pages") stays quiet (S1). No word
  // boundaries, as on main: \b fails beside _, which hid "_Ignore all previous instructions_" (F5).
  // Only these two nouns: "rules", "guidelines" and "prompts" made ordinary prose a BLOCK (re-check G4).
  { re: /ignore\s+(?:(?:all|any)\s+(?:of\s+)?)?(?:the\s+|your\s+|my\s+)?(?:previous|prior|above|earlier|preceding|all|your)\s+(?:instructions|directions)/i,
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
  // whose first target is an absolute or home path (/…, ~…, $HOME…), quoted or not. As on main, /tmp
  // counts too: an exemption was escapable through .., quotes, variables and redirects (final review F3/F4).
  // As on main, rm may follow any non-word character (\rm, (rm, "rm, Makefile's -rm). Separators are \s, so
  // a soft wrap in prose keeps the command (re-check G1). An option run holding --cached before any -- or
  // lone - is git rm, which only untracks (G5); plain rm refuses that option, so no "git" lookbehind is
  // needed (pre-push H2: that lookbehind let "X=git rm -rf /" and "sudo -u git rm -rf ~" through). After
  // -- or -, "--cached" is a file name and rm deletes the rest, so the search stops there (verification V1).
  // Linear: an option token is -(\w | - not followed by rm)*, so no token holds "-rm" and no option run
  // can contain a later rm start (pre-push H1: "--rm" repeated was quadratic); lookaheads (never
  // re-entered) check for a recursive/force option and capture the option run, which \1 then consumes.
  { re: /(?<!\w)rm["']?\s+(?!(?:(?!--?\s)(?!-rm\b)-(?:\w|-(?!rm\b))*\s+)*?--cached\b)(?=(?:(?!-rm\b)-(?:\w|-(?!rm\b))*\s+)*?(?:-[a-zA-Z]*[rRf]|--recursive\b|--force\b))(?=((?:(?!-rm\b)-(?:\w|-(?!rm\b))*\s+)*))\1["']?(?:\/|~|\$\{?HOME\b)/,
                                          name: 'rm-rf-root',       sev: 'BLOCK' },
  // Linear time with no length cap: anchored at a line start (after \n only: the m flag would also start
  // a line after \r and \u2028, which [^\n] reads through, and that was quadratic), a lookahead (never re-entered) finds the
  // line's first curl, then one greedy pass looks for a later pipe into a shell. The old .+ retried
  // every curl on the line and took seconds on a long line of repeated "curl |".
  { re: /(?<![^\n])(?=([^\n]*?curl\s+))\1[^\n]*\|\s*(bash|sh|zsh)\b/, name: 'curl-pipe-shell',  sev: 'BLOCK' },
  { re: /(?<![^\n])(?=([^\n]*?wget\s+))\1[^\n]*\|\s*(bash|sh|zsh)\b/, name: 'wget-pipe-shell',  sev: 'BLOCK' },
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
  // Anthropic keys and tokens: api03, admin01, oat01 (OAuth) … (S7: main knew api03 and admin only). The
  // wider form needs no letter or digit before sk-, so "task-ant-colony-…" prose is quiet (independent
  // review T5); main's form keeps matching anywhere.
  { re: /sk-ant-(?:api03|admin)-[A-Za-z0-9_\-]{20,}|(?<![A-Za-z0-9])sk-ant-[a-z]+\d*-[A-Za-z0-9_\-]{20,}/,
                                                                      name: 'anthropic-api-key',      sev: 'BLOCK' },
  // OpenAI / generic LLM keys: legacy sk-…, and the dashed proj/svcacct/admin forms (S7). The dashed
  // forms need a known prefix and no letter or digit before sk-, so kebab-case prose ("risk-assess…") is quiet.
  { re: /sk-[A-Za-z0-9]{32,}|(?<![A-Za-z0-9])sk-(?:proj|svcacct|admin)-[A-Za-z0-9_\-]{20,}/,
                                                                      name: 'hardcoded-llm-key',      sev: 'BLOCK' },
  // GitHub tokens
  { re: /ghp_[A-Za-z0-9]{36}/,                                        name: 'github-pat-classic',     sev: 'BLOCK' },
  { re: /github_pat_[A-Za-z0-9_]{82}/,                                name: 'github-pat-fine',        sev: 'BLOCK' },
  { re: /gho_[A-Za-z0-9]{36}/,                                        name: 'github-oauth-token',     sev: 'BLOCK' },
  // GitHub App tokens: ghs_ (installation), ghu_ (user-to-server), ghr_ (refresh) (S7)
  { re: /gh[usr]_[A-Za-z0-9]{36}/,                                    name: 'github-app-token',       sev: 'BLOCK' },
  // AWS
  { re: /AKIA[0-9A-Z]{16}/,                                           name: 'aws-access-key-id',      sev: 'BLOCK' },
  // Slack
  { re: /xoxb-[0-9]{10,13}-[0-9]{10,13}-[A-Za-z0-9]{24}/,           name: 'slack-bot-token',        sev: 'BLOCK' },
];

// ─── Config: Overly permissive settings.json rules ─────────────────────────
// Applied only to files named settings.json / settings.local.json.
// An entry with allowRule is a permission check. When readSettings can read the file, allowRule is
// tested against each permissions.allow rule (trimmed; the bare tool name, S4), and re against the raw
// text with the permissions.deny and permissions.ask arrays emptied. Otherwise re is tested against the
// raw text, as on main.
// Docs (code.claude.com/docs/en/permissions, read 2026-10-16): "`Bash(*)` is equivalent to `Bash` and
// matches all Bash commands"; ":*" is an equivalent way to write a trailing wildcard; "//path" is an
// absolute path, "~/path" is under home, and "/path" is relative to the settings source.
const CONFIG_PATTERNS = [
  // Wildcard tool allow rules — grants Claude unrestricted access. The bare name is the same rule (S4).
  { re: /"Bash\(\*\)"/,  allowRule: /^Bash(?:\([\s*:]*\))?$/i,   name: 'perm-bash-wildcard',       sev: 'BLOCK' },
  { re: /"Write\(\*\)"/, allowRule: /^Write(?:\([\s*:]*\))?$/i,  name: 'perm-write-wildcard',      sev: 'BLOCK' },
  { re: /"Edit\(\*\)"/,  allowRule: /^Edit(?:\([\s*:]*\))?$/i,   name: 'perm-edit-wildcard',       sev: 'BLOCK' },
  { re: /"Read\(\*\)"/,  allowRule: /^Read(?:\([\s*:]*\))?$/i,   name: 'perm-read-wildcard',       sev: 'FLAG'  },
  // Permission bypass mode — removes all confirmation prompts
  { re: /"bypassPermissions"/,                   name: 'perm-bypass-mode',         sev: 'BLOCK' },
  // Wildcard in allow array (current Claude Code skips an unanchored allow glob with a warning; older
  // versions may not, so it stays a BLOCK)
  { re: /"allow"\s*:\s*\[\s*(?:[^[\]]*,\s*)?"(?:\*|Bash\(\*\)|Write\(\*\))"/, allowRule: /^\*+$/,
                                                 name: 'perm-allow-wildcard',      sev: 'BLOCK' },
  // Hardcoded Anthropic key or token anywhere in config (S7: oat01 and admin01 too)
  { re: /sk-ant-(?:api03|admin)-[A-Za-z0-9_\-]{20,}|(?<![A-Za-z0-9])sk-ant-[a-z]+\d*-[A-Za-z0-9_\-]{20,}/,
                                                 name: 'anthropic-key-in-config',  sev: 'BLOCK' },
  // Broad path permissions: the settings source's root, anything under home, any absolute path (//)
  { re: /"(?:Write|Edit)\(\/\*?\)"|"(?:Write|Edit)\(~\//, allowRule: /^(?:Write|Edit)\((?:\/\*?\)|~\/|\/\/)/,
                                                 name: 'perm-broad-path',          sev: 'FLAG'  },
  // Hook command with shell substitution — potential injection vector
  // $( … ) inside the command string, escape-aware (\" does not end it). Linear: a lookahead finds the
  // first $( once, and the closing ) must come before the string ends (main's [^"]*…[^)]* was quadratic).
  { re: /"command"\s*:\s*"(?=((?:[^"\\]|\\.)*?\$\())\1(?:[^)"\\]|\\.)*\)/,
                                                 name: 'hook-shell-substitution',  sev: 'FLAG'  },
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

// Finds a shell=True keyword argument inside a subprocess.run/call/Popen/check_output/check_call
// call, at any depth (subprocess.run(wrap(shell=True)) counts, as on main). One pass over the file
// with a stack of open brackets, so it is linear: strings (', ", triple-quoted, with backslash
// escapes) and # comments are skipped, which also stops a ) or a "shell=True" inside them from
// counting. Returns a match-like array (m[0] is the call's start) or null.
const PY_SUBPROCESS_CALL = /subprocess\s*\.\s*(?:run|call|Popen|check_output|check_call)\s*$/;
const COMMENT_REST = /[^\r\n]*/y;
const PY_SHELL_TRUE = /^shell\s*=\s*True(?![A-Za-z0-9_])/;
// main's pattern (re-check G2 and F8), plus the word end after True
const PY_SHELL_TRUE_MAIN = /subprocess\.(?:run|call|Popen|check_output|check_call)\((?:(?!subprocess\.(?:run|call|Popen|check_output|check_call)\()[^)])*?shell\s*=\s*True(?![A-Za-z0-9_])/;
function findPyShellTrue(text) {
  const stack = [];     // one entry per open bracket: the call's start offset when it is a subprocess call, else -1
  let subDepth = 0;     // how many entries in the stack are subprocess calls
  let lastOpen = 0;     // where the text before the next ( starts, so the call-name check reads a short slice
  for (let i = 0; i < text.length; i++) {
    const c = text[i];
    // A comment runs to the line end; Python also ends a line at a lone \r (independent review T2).
    if (c === '#') { COMMENT_REST.lastIndex = i; COMMENT_REST.test(text); i = COMMENT_REST.lastIndex - 1; continue; }
    if (c === '"' || c === "'") {
      const triple = text.startsWith(c.repeat(3), i);
      const end = triple ? c.repeat(3) : c;
      let j = i + end.length;
      for (; j < text.length; j++) {
        if (text[j] === '\\') { j++; continue; }
        if (!triple && (text[j] === '\n' || text[j] === '\r')) break;
        if (text.startsWith(end, j)) { j += end.length - 1; break; }
      }
      i = j;
      continue;
    }
    if (c === '(' || c === '[' || c === '{') {
      let start = -1;
      if (c === '(') {
        const before = text.slice(Math.max(lastOpen, i - 64), i);
        const m = before.match(PY_SUBPROCESS_CALL);
        if (m) start = i - before.length + m.index;
      }
      stack.push(start);
      if (start >= 0) subDepth++;
      lastOpen = i + 1;
      continue;
    }
    if (c === ')' || c === ']' || c === '}') {
      if (stack.length && stack.pop() >= 0) subDepth--;
      lastOpen = i + 1;
      continue;
    }
    if (c === 's' && subDepth > 0 && !/[A-Za-z0-9_.]/.test(text[i - 1] || '')) {
      const m = text.slice(i, i + 64).match(PY_SHELL_TRUE);
      if (m) {
        const start = stack.find(s => s >= 0);
        const hit = [text.slice(start, i + m[0].length)];
        hit.index = start;
        return hit;
      }
    }
  }
  return null;
}

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
  // shell=True as an argument anywhere inside a subprocess call, nested calls included. A regex stopped at
  // the first ), so subprocess.run(build(cmd), shell=True) passed (S8); findPyShellTrue reads the call.
  // main's regex still runs, so a string the reader misreads can only add findings, never hide main's
  // (background security review of dc61b2c: a Python 3.12 f-string nesting ''' hid the rest of the file).
  { find: t => findPyShellTrue(t) || t.match(PY_SHELL_TRUE_MAIN),       name: 'subprocess-shell-true', sev: 'BLOCK' },
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
  { re: /(?<![^\n])(?=([^\n]*?curl\s+))\1[^\n]*\|\s*(bash|sh)\b/, name: 'curl-pipe-shell', sev: 'BLOCK' },
  { re: /(?<![^\n])(?=([^\n]*?wget\s+))\1[^\n]*\|\s*(bash|sh)\b/, name: 'wget-pipe-shell', sev: 'BLOCK' },
  { re: /--break-system-packages/,        name: 'pip-break-system',  sev: 'FLAG'  },
];

// Which text each markdown table reads (S2, and the owner's decision R2 of 2026-10-15):
//   - prompt injection and FLAG-level bash: prose only (markdown code stripped)
//   - BLOCK-level bash: its own severity in prose; FLAG when it appears only in code, fenced or inline.
//     A documented example then asks for confirmation instead of refusing the skill, and a fence-pairing
//     trick can only lower a BLOCK to a FLAG, never hide the command (final review F7)
//   - secrets: the whole file at full severity; a real key leaks wherever it sits
function scanMarkdown(filePath, content) {
  const prose = stripCodeBlocks(content);
  const quote = (m, note = '') => `"${note}${m[0].slice(0, 80).replace(/\n/g, '\\n')}"`;
  for (const { re, name, sev } of [...MD_INJECTION, ...MD_BASH]) {
    const m = prose.match(re);
    if (m) { flag(filePath, name, sev, quote(m)); continue; }
    if (sev !== 'BLOCK' || !MD_BASH.some(p => p.name === name)) continue;
    const c = content.match(re);
    if (c) flag(filePath, name, 'FLAG', quote(c, '(in code) '));
  }
  for (const { re, name, sev } of MD_SECRETS) {
    const m = content.match(re);
    if (m) flag(filePath, name, sev, quote(m));
  }
}

// CONFIG_PATTERNS are applied only to Claude Code settings files.
const CONFIG_FILENAMES = new Set(['settings.json', 'settings.local.json']);

// Reads a settings file that is valid JSON. Returns null when it is not valid JSON; then the permission
// checks read the raw text, as on main. Otherwise returns:
//   allow: the trimmed string rules of every permissions.allow, in every copy of a duplicate key (a
//          reader may keep either copy; keys are compared decoded, so "permissions" counts)
//   text:  the raw text with the permissions.deny and permissions.ask arrays (every copy) emptied, for
//          main's text checks: only deny and ask rules, which grant nothing, stop being reported (S4).
//          A shape the schema rejects (allow as a string, a top-level array) adds no allow rules, and
//          the text checks still read it, as on main (independent review T10)
// A BOM is dropped first, as JSON.parse refuses it. Background security review of c136334: reading
// permissions.allow alone lost main's matches elsewhere ("allowedTools"), and the earlier key renaming
// could collide with a real key.
const JSON_SCALAR = /[^,\]}\s]*/y;
// Builds only what readSettings uses: the top-level object, each permissions object, and its allow,
// deny and ask arrays with their string items and positions. Every other value is skipped by a loop
// that counts brackets, so nesting depth costs nothing: a recursive reader gave up past a few thousand
// levels, and the fallback text checks miss a bare tool name (independent review round 3, W1).
function readJsonTree(text) {
  let i = 0;
  const ws = () => { while (i < text.length && ' \t\n\r'.includes(text[i])) i++; };
  const peek = () => { ws(); return text[i]; };
  // The end of the string that starts at i: the first " after it with an even run of backslashes
  // before it. A loop, not a regex: the regex overflowed the stack on a string of about 8 MB, and the
  // reader then gave up (independent review round 4, X1). Each backslash run is counted once.
  const strEnd = () => {
    for (let q = text.indexOf('"', i + 1); q >= 0; q = text.indexOf('"', q + 1)) {
      let b = q - 1;
      while (text[b] === '\\') b--;                    // stops at the opening quote at the latest
      if ((q - 1 - b) % 2 === 0) return q + 1;
    }
    return text.length;                                // unreachable on valid JSON
  };
  const str = () => { const end = strEnd(); const s = JSON.parse(text.slice(i, end)); i = end; return s; };
  function skip() {
    const c = peek();
    if (c === '"') { i = strEnd(); return { type: 'other' }; }
    if (c !== '{' && c !== '[') { JSON_SCALAR.lastIndex = i; JSON_SCALAR.test(text); i = JSON_SCALAR.lastIndex; return { type: 'other' }; }
    for (let depth = 0; i < text.length; i++) {
      const ch = text[i];
      if (ch === '"') { i = strEnd() - 1; continue; }
      if (ch === '{' || ch === '[') depth++;
      else if ((ch === '}' || ch === ']') && --depth === 0) { i++; break; }
    }
    return { type: 'other' };
  }
  function object(readValue) {
    i++;
    const entries = [];
    if (peek() === '}') { i++; return { type: 'object', entries }; }
    for (;;) {
      ws(); const key = str(); ws(); i++;              // the ':'
      entries.push([key, readValue(key)]);
      if (peek() === '}') { i++; return { type: 'object', entries }; }
      i++;                                             // the ','
    }
  }
  function array(readItem) {
    const start = i++;
    const items = [];
    if (peek() === ']') { i++; return { type: 'array', items, start, end: i }; }
    for (;;) {
      items.push(readItem());
      if (peek() === ']') { i++; return { type: 'array', items, start, end: i }; }
      i++;                                             // the ','
    }
  }
  const listItem = () => (peek() === '"' ? { type: 'string', value: str() } : skip());
  const permValue = key => ((key === 'allow' || key === 'deny' || key === 'ask') && peek() === '[' ? array(listItem) : skip());
  const rootValue = key => (key === 'permissions' && peek() === '{' ? object(permValue) : skip());
  return peek() === '{' ? object(rootValue) : { type: 'other' };
}

function readSettings(content) {
  const text = content.replace(/^\uFEFF/, '');
  let root;
  try { JSON.parse(text); root = readJsonTree(text); } catch { return null; }   // not valid JSON
  const allow = [];
  const blank = [];
  for (const [key, perms] of root.type === 'object' ? root.entries : []) {
    if (key !== 'permissions' || perms.type !== 'object') continue;
    for (const [k, list] of perms.entries) {
      if (list.type !== 'array') continue;
      if (k === 'allow') for (const item of list.items) { if (item.type === 'string') allow.push(item.value.trim()); }
      else if (k === 'deny' || k === 'ask') blank.push(list);
    }
  }
  let out = '', last = 0;
  for (const { start, end } of blank.sort((a, b) => a.start - b.start)) { out += text.slice(last, start) + '[]'; last = end; }
  return { allow, text: out + text.slice(last) };
}

function scanConfig(filePath, content) {
  const settings = readSettings(content);
  for (const { re, allowRule, name, sev } of CONFIG_PATTERNS) {
    if (allowRule && settings) {
      const rule = settings.allow.find(r => allowRule.test(r));
      if (rule !== undefined) { flag(filePath, name, sev, `"allow: ${rule.slice(0, 72)}"`); continue; }
      const m = settings.text.match(re);
      if (m) flag(filePath, name, sev, `"${m[0].slice(0, 80)}"`);
      continue;
    }
    if (re.test(content)) {
      const m = content.match(re);
      flag(filePath, name, sev, `"${m[0].slice(0, 80)}"`);
    }
  }
  // Also check for generic secrets in config files
  scanSecrets(filePath, content);
}

// Data and config files other than settings*.json are read for secrets only (S6).
function scanSecrets(filePath, content) {
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

  for (const { re, find, name, sev } of patterns) {
    const m = find ? find(scanContent) : scanContent.match(re);
    if (m) flag(filePath, name, sev, `"${m[0].slice(0, 80)}"`);
  }
}

// Data and config files read for secrets (S6), by extension or, for dotfiles, by name.
const DATA_EXTS = new Set(['.json', '.jsonc', '.json5', '.yaml', '.yml', '.toml', '.ini', '.cfg', '.conf', '.env', '.properties']);
const DATA_FILENAMES = new Set(['.env', '.npmrc', '.pypirc', '.netrc']);
const isDataFile = (base, ext) => DATA_EXTS.has(ext) || DATA_FILENAMES.has(base) || base.startsWith('.env.');

// A file with no known script extension is read by its shebang (S5): "#!/bin/sh", "#!/usr/bin/env node",
// "#!/usr/bin/env -S node --flag", "#!/usr/bin/python3.12". Returns the extension whose patterns apply.
const SHEBANG_EXT = { node: '.js', nodejs: '.js', deno: '.js', bun: '.js', python: '.py', pypy: '.py',
                      sh: '.sh', bash: '.sh', zsh: '.sh', dash: '.sh', ksh: '.sh', ash: '.sh' };
function shebangExt(content) {
  const m = content.match(/^#!\s*([^\n]*)/);
  if (!m) return '';
  const words = m[1].trim().split(/\s+/);
  let prog = path.basename(words[0] || '');
  if (prog === 'env') prog = path.basename(words.slice(1).find(w => !w.startsWith('-') && !w.includes('=')) || '');
  return SHEBANG_EXT[prog.replace(/^(python|pypy)[\d.]*$/, '$1')] || '';
}

function scanFile(full, content) {
  const ext  = path.extname(full).toLowerCase();
  const base = path.basename(full).toLowerCase();
  if (['.md', '.txt'].includes(ext))   scanMarkdown(full, content);
  else if (CONFIG_FILENAMES.has(base)) scanConfig(full, content);
  // Script extensions first: a script named .env.sh or .env.local.js keeps its table (independent review T3)
  else if (JS_EXTS.has(ext) || PY_EXTS.has(ext) || SH_EXTS.has(ext)) scanScript(full, content, ext);
  else if (isDataFile(base, ext))      scanSecrets(full, content);
  else                                 scanScript(full, content, shebangExt(content));
}

// S10: content the scanner cannot check is a finding, never skipped silently. What it could not
// read at all (unreadable, special-file) is BLOCK: main crashed or hung there, which fails closed,
// and a FLAG would let unchecked content through. What it read with a caveat (file-too-large,
// symlink-outside-tree) is FLAG. These checks only add to what main reported: every file main
// read is still read the same way, so a verdict is never lower than main's.
// - A file too large to read whole (past about 536 MB, node's string limit) used to be dropped
//   and pass. It is now scanned in overlapping chunks and reported. Past MAX_SCAN_BYTES it is not
//   read at all (BLOCK): scan time grows with size, and main passed such files unread.
// - A FIFO, socket or device is never opened: opening a FIFO waits for a writer forever.
// - A symlink to a file is read through the link and scanned under the link's name, as main
//   did: that is the name Claude Code loads it by. A symlink to a directory is never walked: the
//   tree's own directories are walked in place.
// - A symlink that leaves the tree is BLOCK (owner decision 2026-10-20): install copies the link
//   as is, so what Claude Code loads after install is not what was audited. It leaves the tree if
//   it is absolute (after install it points back at the audit location), if its relative path
//   climbs out of the tree (even to come back in by name), if it resolves outside, or if it is
//   dangling or loops. A file target is still scanned, and its matches are not quoted.
// - A file or directory that cannot be read is reported.
const CHUNK_BYTES = 64 * 1024 * 1024;
const MAX_SCAN_BYTES = 2 * 1024 * 1024 * 1024;   // larger files are not read: a 2.5 GB scan took 45 s
const OVERLAP_BYTES = 1024 * 1024;
let treeRoot = null;
try { treeRoot = isSingleFile ? null : fs.realpathSync(skillDir); } catch { /* reported by walkDir */ }
let quoteMatches = true;

const within = (root, p) => p === root || p.startsWith(root + path.sep);
// Why a symlink leaves the tree, or '' when it stays inside: a relative link whose path stays in
// the tree and resolves inside it. A link in the tree is checked when it is walked, so a chain
// through another link is caught at that link too.
function leavesTree(full) {
  const target = linkTarget(full);
  if (path.isAbsolute(target)) return 'an absolute link';
  // Walk the link's path from its directory: a ".." above the tree's top climbs out, even when a
  // later part comes back in by the tree's name (that name changes on install).
  let depth = path.relative(path.resolve(skillDir), path.resolve(path.dirname(full))).split(path.sep).filter(Boolean).length;
  for (const part of target.split(/[\\/]/)) {
    if (part === '..' && --depth < 0) return 'its path climbs out of the scanned tree';
    if (part && part !== '.' && part !== '..') depth++;
  }
  if (!treeRoot) return 'outside the scanned tree';
  try { return within(treeRoot, fs.realpathSync(full)) ? '' : 'it resolves outside the scanned tree'; }
  catch { return 'outside the scanned tree'; }
}
function linkTarget(full) {
  try { return fs.readlinkSync(full); } catch { return '?'; }
}
function specialKind(st) {
  if (st.isFIFO()) return 'a FIFO';
  if (st.isSocket()) return 'a socket';
  if (st.isCharacterDevice() || st.isBlockDevice()) return 'a device';
  return 'not a regular file';
}
const errText = e => e.code || e.message;

// Past node's string limit: scan overlapping chunks, keep one finding per check, and report it.
function scanInChunks(full, size) {
  const before = findings.length;
  let fd;
  try { fd = fs.openSync(full, 'r'); }
  catch (e) { flag(full, 'unreadable', 'BLOCK', `"${errText(e)}; not scanned"`, true); return; }
  const buf = Buffer.alloc(CHUNK_BYTES);
  try {
    for (let pos = 0; ; pos += CHUNK_BYTES - OVERLAP_BYTES) {
      const n = fs.readSync(fd, buf, 0, CHUNK_BYTES, pos);
      if (n > 0) scanFile(full, buf.toString('utf8', 0, n));
      if (n < CHUNK_BYTES) break;
    }
  } catch (e) {
    flag(full, 'unreadable', 'BLOCK', `"${errText(e)}; partly scanned"`, true);
  } finally { fs.closeSync(fd); }
  // One finding per check, the most severe: rm-rf-root is FLAG in a code block and BLOCK in prose.
  const seen = new Set();
  const rank = f => (f.severity === 'BLOCK' ? 0 : 1);
  findings.push(...findings.splice(before).sort((a, b) => rank(a) - rank(b))
    .filter(f => !seen.has(f.check) && seen.add(f.check)));
  flag(full, 'file-too-large', 'FLAG', `"${size} bytes, too large to read whole; scanned in chunks of ${CHUNK_BYTES} bytes overlapping by ${OVERLAP_BYTES}, so a longer match can be missed"`, true);
}

function readAndScan(full, size) {
  let content;
  try { content = fs.readFileSync(full, 'utf8'); }
  catch (e) {
    if (e.code === 'ERR_STRING_TOO_LONG' || e.code === 'ERR_FS_FILE_TOO_LARGE') scanInChunks(full, size);
    else flag(full, 'unreadable', 'BLOCK', `"${errText(e)}; not scanned"`, true);
    return;
  }
  scanFile(full, content);
}

// st comes from lstat for an entry of the tree and from stat for the named target.
function scanPath(full, st) {
  let outside = false;
  if (st.isSymbolicLink()) {
    const why = (target) => `"links to ${linkTarget(full).slice(0, 80)}; ${target}, so the installed copy would not load what was audited"`;
    let target;
    try { target = fs.statSync(full); }
    catch (e) { flag(full, 'symlink-outside-tree', 'BLOCK', why(`${errText(e)} (dangling or a loop)`), true); return; }
    const reason = leavesTree(full);
    outside = reason !== '';
    if (outside) flag(full, 'symlink-outside-tree', 'BLOCK', why(target.isDirectory() ? `${reason}; a directory, not walked` : `${reason}; scanned under this name`), true);
    if (target.isDirectory()) return;
    st = target;
  }
  if (st.isDirectory()) { walkDir(full); return; }
  if (!st.isFile()) { flag(full, 'special-file', 'BLOCK', `"${specialKind(st)}; not read"`, true); return; }
  if (st.size > MAX_SCAN_BYTES) {
    flag(full, 'file-over-scan-limit', 'BLOCK', `"${st.size} bytes, over the ${MAX_SCAN_BYTES}-byte scan limit; not read"`, true);
    return;
  }
  quoteMatches = !outside;
  try { readAndScan(full, st.size); } finally { quoteMatches = true; }
}

function walkDir(dir) {
  let names;
  try { names = fs.readdirSync(dir); }
  catch (e) { flag(dir, 'unreadable', 'BLOCK', `"${e.code || e.message}; directory not scanned"`, true); return; }
  for (const name of names) {
    const full = path.join(dir, name);
    let st;
    try { st = fs.lstatSync(full); }
    catch (e) { flag(full, 'unreadable', 'BLOCK', `"${e.code || e.message}; not scanned"`, true); continue; }
    scanPath(full, st);
  }
}

// Support single-file scanning (agent .md, settings.json) as well as directories
if (isSingleFile) scanPath(skillDir, targetStat);
else walkDir(skillDir);

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
