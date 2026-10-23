#!/usr/bin/env node
// static-scan.js <skill-dir|agent-file|config-file>
// Deterministic security scanner for Claude Code skill directories, agent files,
// and configuration files. Pattern categories:
//   - Prompt injection / persona override (MD_INJECTION)
//   - Dangerous Bash in instructions (MD_BASH), unpinned installs included (unpinned-install, P0-02)
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
const checksByFile = new Map();   // file -> checks reported, so scanSecrets need not search findings (review P2)
// The target itself is followed if it is a symlink: the user named it. Anything that is not a
// directory is scanned as a single file, so a FIFO or an unreadable file is reported (S10).
const targetStat = fs.statSync(skillDir);
const isSingleFile = !targetStat.isDirectory();
// A single-file scan names the file itself; relative to the file, every finding had file: "" (S9).
const findingRoot = isSingleFile ? path.dirname(skillDir) : skillDir;

// own: the detail is the scanner's own text (a size, an error code), not quoted content.
function flag(file, check, severity, detail, own = false) {
  // Matches read through a link that leaves the tree are not quoted: the target can be any file (S10).
  if (!quoteMatches && !own) detail = '"(match through a link that leaves the scanned tree; not quoted)"';
  // The scanned directory itself is "." (an unreadable root), never an empty name.
  const rel = path.relative(findingRoot, file) || '.';
  findings.push({ file: rel, check, severity, detail });
  if (!checksByFile.has(rel)) checksByFile.set(rel, new Set());
  checksByFile.get(rel).add(check);
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

// ─── Unpinned installs (P0-02) ─────────────────────────────────────────────
// One check, unpinned-install, for code fetched at run time without an exact version:
//   - npx <pkg> unless <pkg> ends in @x.y.z (a prerelease or build suffix is allowed): a range (@^1, @~1),
//     a partial version (@1.2) or none is a hit. A scope (@scope/pkg) and quotes are allowed. A path (./x) is
//     not a package. With -p/--package, every -p value is read and the positional is a command, not a package.
//   - pip install (pip, pip3, pip3.12, python -m pip, uv pip): every word after install is read. A word with ==,
//     a path (. / ~), an option, a redirect (2>x) and the argument of a pip flag that takes one (-r, -c, -t, -i,
//     -f, -C and the long forms in PIP_ARG_FLAG) are skipped; the first other word is the package, a hit. A word
//     the read cannot place (<pkg>, $VAR, 2>&1) ends the read.
//   - <pkg>@latest anywhere.
// Curl or wget piped to a shell is curl-pipe-shell / wget-pipe-shell below, not repeated here.
// Words may be separated by blanks or a backslash-newline continuation. npx, pip and uv may be written in any
// case (a case-insensitive file system runs NPX as npx).
// npx and pip count only in command position: a line start, or just after a backtick, ;, &, |, (, { or !;
// then an optional list or quote marker (-, *, +, >, 1.), a "$ " prompt, and command prefixes (VAR=val, env,
// exec, time, command, nohup, sudo, an option word such as -E, and sh/bash -c "…"). So prose that names the
// tool mid-sentence ("access to npx", "Install: npx x") is quiet: a tripwire, not a boundary, like rm-rf-root.
// Prose that starts a line or a table cell with the tool name is read as a command (a known false positive).
// Linear: a word (T) cannot hold a blank, backslash or any command-start character, and a line that follows a
// backslash-newline is not a command start, so no run of words can contain a later command start. Every
// repeated part has one parse: npx options exclude -p; pip's skip kinds are told apart by their first
// character or a lookahead, and a pip flag that takes an argument is never read as a plain option. The
// command-start anchor is what keeps this linear: without it, an earlier form took 350 s on 1 MB of "npx<TAB>-".
const SP = String.raw`(?:[ \t]|\\\r?\n)`;
const T = String.raw`[^\s\x60;&|(){}!\\]`;
const PIP_ARG_FLAG = String.raw`-[rctCif]|--(?:requirement|constraint|target|platform|python-version|implementation|abi|root|` +
  String.raw`prefix|src|upgrade-strategy|config-settings|global-option|no-binary|only-binary|progress-bar|root-user-action|` +
  String.raw`report|index-url|extra-index-url|find-links|log|proxy|retries|timeout|exists-action|trusted-host|cert|` +
  String.raw`client-cert|cache-dir|use-feature|use-deprecated|keyring-provider|python|resume-retries|group)`;
const OPT_TOKEN = String.raw`-${T}*${SP}+`;
const SH_C = String.raw`(?:ba|z|da|k)?sh${SP}+-[A-Za-z]*c${SP}+["']`;
const PREFIX = String.raw`(?:(?:[A-Za-z_]\w*=${T}*|env|exec|time|command|nohup|sudo|-[A-Za-z][\w-]*)${SP}+|${SH_C})*`;
const CMD_AT = String.raw`(?:(?<![^\n])(?<!\\\n)(?<!\\\r\n)|(?<=[\x60;&|({!]))[ \t]*(?:(?:[-*+>]|\d+[.)])[ \t]+)?` +
  String.raw`(?:\$[ \t]+)?${PREFIX}`;
// The exact version may be quoted and followed by sentence punctuation (".", ",", ":") before the word ends.
const EXACT_NPM = String.raw`["']?(?:@[\w.-]+\/)?[\w.-]+@\d+\.\d+\.\d+(?:[-+][\w.+-]*)?["']?[.,:]?(?![^\s\x60'"();&|\\])`;
const NPX_PKG = String.raw`(?!${EXACT_NPM})["']?(?:@[\w.-]+\/)?[A-Za-z0-9]`;
const NPX_P = String.raw`(?:-p|--package)(?:=|${SP}+)`;
const NPX_OPT = String.raw`(?!(?:-p|--package)(?:=|${SP}))${OPT_TOKEN}`;
const NPX_UNPINNED = String.raw`[Nn][Pp][Xx]${SP}+(?:${NPX_OPT})*` +
  String.raw`(?:${NPX_PKG}|(?:${NPX_P}(?=${EXACT_NPM})${T}+${SP}+(?:${NPX_OPT})*)*${NPX_P}${NPX_PKG})`;
const PIP_SKIP = String.raw`(?:(?:${PIP_ARG_FLAG})${SP}+${T}+${SP}+|(?!(?:${PIP_ARG_FLAG})${SP})${OPT_TOKEN}|` +
  String.raw`[./~]${T}*${SP}+|\d*[<>](?:${T}+|${SP}+${T}+)${SP}+|(?![-./~]|\d*[<>])(?=${T}*==)${T}+${SP}+)`;
const PIP_UNPINNED = String.raw`(?:[Pp][Yy][Tt][Hh][Oo][Nn][\d.]*${SP}+-m${SP}+|[Uu][Vv]${SP}+)?` +
  String.raw`[Pp][Ii][Pp][\d.]*${SP}+[Ii][Nn][Ss][Tt][Aa][Ll][Ll]${SP}+${PIP_SKIP}*` +
  String.raw`(?!\d*[<>])["']?(?!${T}*==)[A-Za-z0-9]`;
// A full stop ends it too ("…@latest."), but a name goes on after one ("user@latest.test").
const AT_LATEST = String.raw`[\w.\/-]@latest(?![\w-]|\.[\w-])`;
const UNPINNED_INSTALL = new RegExp(`${CMD_AT}(?:${NPX_UNPINNED}|${PIP_UNPINNED})|${AT_LATEST}`);

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
  { re: UNPINNED_INSTALL,                 name: 'unpinned-install', sev: 'BLOCK' },
  { re: /\bsudo\s+/,                      name: 'sudo',             sev: 'FLAG'  },
  { re: /chmod\s+[0-7]{3}\s/,            name: 'chmod',            sev: 'FLAG'  },
  { re: /~\/.ssh\//,                      name: 'ssh-dir-access',   sev: 'BLOCK' },
  { re: /~\/.claude\/settings/,          name: 'settings-write',   sev: 'FLAG'  },
];

// ─── Markdown/Config: Hardcoded secrets ────────────────────────────────────
const MD_SECRETS = [
  // Generic patterns. The name may be quoted, as a JSON key is: "password": "…" (S13), and may carry a
  // key suffix: SECRET_KEY, AWS_SECRET_ACCESS_KEY, secretKey, private_key (review Q1).
  { re: /(?:api[_-]?key|apikey)['"]?\s*[:=]\s*['"][A-Za-z0-9_\-]{16,}/i,  name: 'hardcoded-api-key',     sev: 'FLAG'  },
  { re: /(?:password|passwd|secret|token|private[_-]?key)(?:[_-]?(?:access[_-]?)?key)?['"]?\s*[:=]\s*['"][^'"]{8,}/i,
                                                                      name: 'hardcoded-secret',       sev: 'FLAG'  },
  // npm's environment form of _auth: NPM_CONFIG__AUTH sets _auth (npm 12.1.0, measured 2026-10-21). A pattern
  // of its own, so main's generic pattern still reports the line it reported before (review V9).
  { re: /npm_config__auth['"]?\s*[:=]\s*['"][^'"]{8,}/i,                 name: 'hardcoded-secret',       sev: 'FLAG', extra: true },
  // A basic-auth credential (user:pass, or its base64): basic_auth, basic-auth, basicAuth. The words a
  // config uses for a switch (disabled, required, optional) are not one, nor is the scheme's own name
  // (an enum member BasicAuth = 'BasicAuth', review V4). Each pattern that matches reports, as for the
  // other generic forms, so one line never hides another (review V1).
  { re: /basic[_-]?auth['"]?\s*[:=]\s*['"](?!(?:disabled|required|optional|basic[_-]?auth)(?:['"\s]|$))[^'"]{8,}/i,
                                                                      name: 'hardcoded-secret',       sev: 'FLAG', extra: true },
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
  // npm access tokens: "npm" + "_" + GitHub's token alphabet (base62), the last six a CRC32 checksum
  // (github.blog, "Announcing npm's new access token format", read 2026-10-20; 178 bits of entropy
  // is 30 base62 characters + 6 = 36, as for ghp_). Not glued to a word or a longer run (S13).
  { re: /(?<![A-Za-z0-9_])npm_[A-Za-z0-9]{36}(?![A-Za-z0-9])/,     name: 'npm-token',              sev: 'BLOCK' },
];

// ─── Secrets without quotes, in data and config files only (S13) ───────────
// .env, .npmrc, YAML and INI values are often unquoted: PASSWORD=hunter2, _authToken=…, password: x.
// Markdown keeps the quoted forms only (prose "password: required" is not a secret). A value that
// starts like a placeholder ($VAR, ${VAR}, <…>, {{ … }}, %(…)s) is not a secret. Only spaces and tabs
// may surround the separator, so a YAML key followed by a nested block is not read as its value.
const DATA_SECRETS = [
  { re: /(?:api[_-]?key|apikey)['"]?[ \t]*[:=][ \t]*[A-Za-z0-9_\-]{16,}/i,                name: 'hardcoded-api-key', sev: 'FLAG' },   // its value class already excludes $ < { %
  // SECRET_KEY, AWS_SECRET_ACCESS_KEY, secretKey, PRIVATE_KEY and an .npmrc _auth too (review P4). A
  // value starting with "-" is the default of a ${VAR:-default}, not the secret (review P5).
  // _auth only at the start of a name, as .npmrc writes it, not inside enable_auth (review Q2).
  { re: /(?:password|passwd|secret|token|(?<![A-Za-z0-9_])_auth|private[_-]?key)(?:[_-]?(?:access[_-]?)?key)?['"]?[ \t]*[:=][ \t]*(?![$<{%'"-])[^\s'"#;,]{8,}/i,
                                                                                            name: 'hardcoded-secret',  sev: 'FLAG' },
  // npm's environment form of _auth (NPM_CONFIG__AUTH), a pattern of its own (review V9).
  { re: /npm_config__auth['"]?[ \t]*[:=][ \t]*(?![$<{%'"-])[^\s'"#;,]{8,}/i,                  name: 'hardcoded-secret',  sev: 'FLAG', extra: true },
  { re: /basic[_-]?auth['"]?[ \t]*[:=][ \t]*(?![$<{%'"-])(?!(?:disabled|required|optional|basic[_-]?auth)(?![^\s'"#;,]))[^\s'"#;,]{8,}/i,
                                                                                            name: 'hardcoded-secret',  sev: 'FLAG', extra: true },
];

// .netrc ("machine h login u password X", anywhere on a line) and .properties ("password X" or
// "ssl.password X", a key at the line start; # and ! start a comment) also separate a name from its value
// by spaces alone (review P4, Q3).
const NETRC_SECRET = /(?:^|\s)password[ \t]+(?![$<{%'"=:-])[^\s'"#;,]{8,}/i;
const PROPERTIES_SECRET = /^[ \t]*(?:[\w-]+\.)*(?:password|passwd)[ \t]+(?![$<{%'"=:-])[^\s'"#;,]{8,}/im;

// ─── Secrets in code: the generic forms, stricter (review P3) ──────────────
// In scripts and other code the quoted value must be one closed string without spaces, so a prompt
// ("Password: "), a format string ("Bearer %s") or a string that ends where code goes on
// ("access_token=" + tok) is not a secret. Main never read scripts for secrets, so nothing is lost.
const SCRIPT_SECRETS = [
  { re: /(?:api[_-]?key|apikey)['"]?\s*[:=]\s*['"][A-Za-z0-9_\-]{16,}['"]/i, name: 'hardcoded-api-key', sev: 'FLAG' },
  { re: /(?:password|passwd|secret|token|private[_-]?key)(?:[_-]?(?:access[_-]?)?key)?['"]?\s*[:=]\s*['"][^'"\s]{8,}['"]/i,
                                                                                 name: 'hardcoded-secret',  sev: 'FLAG' },
  { re: /npm_config__auth['"]?\s*[:=]\s*['"][^'"\s]{8,}['"]/i,             name: 'hardcoded-secret',  sev: 'FLAG', extra: true },
  { re: /basic[_-]?auth['"]?\s*[:=]\s*['"](?!(?:disabled|required|optional|basic[_-]?auth)['"])[^'"\s]{8,}['"]/i,
                                                                                 name: 'hardcoded-secret',  sev: 'FLAG', extra: true },
];
const GENERIC_SECRET_CHECKS = new Set(SCRIPT_SECRETS.map(p => p.name));

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
  { re: UNPINNED_INSTALL,                 name: 'unpinned-install',  sev: 'BLOCK' },
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

// Every file is read for secrets (S6, S12, review P1). kind picks the generic forms: 'data' adds the
// unquoted DATA_SECRETS (data and config files, S13), 'code' swaps in the stricter SCRIPT_SECRETS
// (scripts and files of no known type), 'config' (settings*.json) keeps main's. A check already
// reported for the file (a script table's own hardcoded-secret, or the quoted form) is not repeated.
const CODE_SECRETS = [...SCRIPT_SECRETS, ...MD_SECRETS.filter(p => !GENERIC_SECRET_CHECKS.has(p.name))];
function scanSecrets(filePath, content, kind = 'config') {
  const rel = path.relative(findingRoot, filePath) || '.';
  const seen = checksByFile.get(rel) || new Set();
  const table = kind === 'data' ? [...MD_SECRETS, ...DATA_SECRETS] : kind === 'code' ? CODE_SECRETS : MD_SECRETS;
  // mainSecret: a hardcoded-secret from one of main's patterns. The basic-auth and npm patterns (extra) do not
  // stop the space-separated .netrc/.properties check, so their line, a placeholder included, never hides a
  // password line main would show (review V11).
  let mainSecret = seen.has('hardcoded-secret');
  for (const { re, name, sev, extra } of table) {
    if (seen.has(name)) continue;
    const m = content.match(re);
    if (m) flag(filePath, name, sev, `"${m[0].slice(0, 80)}"`);
    if (m && !extra && name === 'hardcoded-secret') mainSecret = true;
  }
  const base = path.basename(filePath).toLowerCase();
  const spaced = kind !== 'data' ? null : base === '.netrc' ? NETRC_SECRET : path.extname(base) === '.properties' ? PROPERTIES_SECRET : null;
  if (spaced && !mainSecret) {
    const m = content.match(spaced);
    if (m) flag(filePath, 'hardcoded-secret', 'FLAG', `"${m[0].trim().slice(0, 80)}"`);
  }
}

function scanScript(filePath, content, ext) {
  let patterns = [];
  let scanContent = content;
  if (JS_EXTS.has(ext)) { patterns = JS_PATTERNS; scanContent = stripRegexLiterals(content); }
  if (PY_EXTS.has(ext)) patterns = PY_PATTERNS;
  if (SH_EXTS.has(ext)) patterns = SH_PATTERNS;
  for (const { re, find, name, sev } of patterns) {
    const m = find ? find(scanContent) : scanContent.match(re);
    if (m) flag(filePath, name, sev, `"${m[0].slice(0, 80)}"`);
  }
  // Secrets in scripts and in files of no known type (S12, review P1), read in the raw text: a key
  // inside a JS regex literal is still a key.
  scanSecrets(filePath, content, 'code');
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
  else if (isDataFile(base, ext))      scanSecrets(full, content, 'data');
  else                                 scanScript(full, content, shebangExt(content));
}

// S10: content the scanner cannot check is a finding, never skipped silently. What it could not
// read at all (unreadable, special-file, file-over-scan-limit) is BLOCK: main crashed or hung
// there, or passed it unread, and a FLAG would let unchecked content through. A symlink that
// leaves the tree is BLOCK too. A file read in chunks (file-too-large) is FLAG. These checks only
// add to what main reported: every file main read is still read the same way, so a verdict is
// never lower than main's.
// - A file too large to read whole (past about 536 MB, node's string limit) used to be dropped
//   and pass. It is now scanned in overlapping chunks and reported. Past MAX_SCAN_BYTES it is not
//   read at all (BLOCK): scan time grows with size, and main passed such files unread.
// - A FIFO, socket or device is never opened: opening a FIFO waits for a writer forever.
// - A symlink to a file is read through the link and scanned under the link's name, as main
//   did: that is the name Claude Code loads it by. A symlink to a directory is never walked: the
//   tree's own directories are walked in place.
// - A symlink that leaves the tree is BLOCK (owner decision 2026-10-20): install copies the link
//   as is, so what Claude Code loads after install is not what was audited. It leaves the tree if
//   it is absolute (after install it points back at the audit location), or if resolving it goes
//   above the tree's top (even to come back in by name), or if it is dangling or loops; see
//   leavesTree. A file target is still scanned, and its matches are not quoted.
// - A file or directory that cannot be read is reported.
const CHUNK_BYTES = 64 * 1024 * 1024;
const MAX_SCAN_BYTES = 2 * 1024 * 1024 * 1024;   // larger files are not read: a 2.5 GB scan took 45 s
const OVERLAP_BYTES = 1024 * 1024;
let quoteMatches = true;

// Why a symlink leaves the tree, or '' when it stays inside. The link is resolved the way the OS
// resolves it, one component at a time from the tree's top, following every symlink on the way:
// ".." after a directory link goes to the parent of that link's target, not to the parent in the
// text. node's fs.realpathSync and a text walk both fold ".." first and so disagree with the OS
// (security review of cc700f8). A ".." above the top, an absolute link, a missing component or
// more than 40 links leaves the tree. A path that never goes above the top resolves the same after
// install, whatever the tree is called or wherever it is copied.
const SPLIT = path.sep === '\\' ? /[\\/]/ : /\//;      // on POSIX a backslash is part of a name
function leavesTree(full) {
  const top = path.resolve(skillDir);
  const at = path.relative(top, path.dirname(path.resolve(full))).split(path.sep).filter(Boolean);
  let target = linkTarget(full);
  if (path.isAbsolute(target)) return 'an absolute link';
  const parts = target.split(SPLIT);
  for (let hops = 0; parts.length;) {
    const part = parts.shift();
    if (part === '' || part === '.') continue;
    if (part === '..') {
      if (!at.length) return 'its path climbs above the scanned tree';
      at.pop();
      continue;
    }
    const next = path.join(top, ...at, part);
    let st;
    // Defensive: the OS already resolved this link (the caller's statSync), so a component cannot
    // be missing unless the tree changes during the scan.
    try { st = fs.lstatSync(next); } catch { return 'a missing path'; }
    if (!st.isSymbolicLink()) { at.push(part); continue; }
    if (++hops > 40) return 'a symlink loop';
    target = linkTarget(next);
    if (path.isAbsolute(target)) return 'it passes through an absolute link';
    parts.unshift(...target.split(SPLIT));
  }
  return '';
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

// exitCode, not process.exit(): on macOS a pipe is written asynchronously, and exit() cut the report at
// 64 KiB (review P8).
process.exitCode = verdict === 'BLOCK' ? 2 : verdict === 'FLAG' ? 1 : 0;
