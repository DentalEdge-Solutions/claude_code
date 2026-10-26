#!/usr/bin/env node
// scripts/staged-deploys.test.js — P0-08: no skill or agent definition deploys a skill itself.
//
// skill-refine's KEEP, skill-refine-agent's KEEP and skill-adapt's step 10 copied the skill into ~/.claude/skills/,
// where Claude Code loads it, with no owner approval in between (S5 P0-08, breach (c)). They now stage the result:
// it stays in skills/<name>/, the step records that it is staged, and deployment waits for owner approval. The
// owner's deploy instruction lives in CLAUDE.md (and in the CLAUDE.md section install.sh writes into targets),
// which legitimately name the path; install.sh's own sync is a script, out of scope here, and prompted by P0-07.
// Record: docs/evaluations/2026-10-26-p0-07-p0-08-ask-rules-staged-deploys.md.
//
// The matcher reads command text. It finds a copy written as a command (cp, rsync, install, ln, mv, ditto) whose
// destination is the user-level skills folder in the spellings listed in USER_SKILLS. It is a check on the
// definitions' text, not a boundary: a definition could still tell the model to deploy in words this test does
// not read. The step-wording checks below pin the three steps that used to deploy.
'use strict';
const assert = require('assert');
const fs = require('fs');
const os = require('os');
const path = require('path');

const REPO = path.join(__dirname, '..');

// A copy command: its name, then its arguments up to a shell separator or a closing backtick.
const COPY = /\b(cp|rsync|install|ln|mv|ditto)\b((?:[ \t]+[^\s`;|&]+)+)/g;
// GNU cp, mv, install and ln take the destination first with -t DIR, a flag cluster ending in t (-Rt DIR) or
// --target-directory[=]DIR (review PR6-R-5). rsync's -t means "keep times" and takes no value.
const TARGET_FIRST = new Set(['cp', 'mv', 'install', 'ln']);
const REDIRECT = /^(?:\d*|&)[<>]/;   // 2>/dev/null, >log; a bare "2>" also takes the next operand
// The user-level skills folder: home by any spelling, or the config folder variable.
const USER_SKILLS = /^["']?(?:~|\$HOME|\$\{HOME\}|\/Users\/[^/]+|\/home\/[^/]+|\/root)["']?\/\.claude\/skills(?:\/|["']?$)|^["']?\$\{?CLAUDE_CONFIG_DIR\b[^}/]*(?:\}|[^}]*\})?["']?\/skills(?:\/|["']?$)/;

// The destination of one copy command: its target-directory value if it has one, else its last operand.
function destination(cmd, args) {
  const out = [];
  const words = args.trim().split(/[ \t]+/);
  for (let i = 0; i < words.length; i++) {
    const w = words[i];
    if (REDIRECT.test(w)) { if (/[<>]$/.test(w)) i++; continue; }
    if (TARGET_FIRST.has(cmd)) {
      if (w.startsWith('--target-directory=')) return w.slice('--target-directory='.length);
      if (w === '--target-directory' || /^-[A-Za-z]*t$/.test(w)) return words[i + 1];
    }
    if (!w.startsWith('-')) out.push(w);
  }
  return out.length >= 2 ? out[out.length - 1] : undefined;
}

// A cd (or pushd) into a folder, then the rest of that line after `&&` or `;`.
const CD_THEN = /\b(?:cd|pushd)[ \t]+(\S+)[ \t]*(?:&&|;)([^\n`]*)/g;
// A destination relative to the folder the cd entered: not absolute, not home, not a variable.
const RELATIVE = /^["']?(?![/~$])/;

// The copy commands in `text` whose destination is the user-level skills folder, written directly or reached
// through a cd into that folder earlier on the same line (review PR6-R-5).
function userSkillsCopies(text) {
  const joined = text.replace(/\\\r?\n[ \t]*/g, ' ');   // shell line continuations joined
  const bad = [];
  for (const m of joined.matchAll(COPY)) {
    const dst = destination(m[1], m[2]);
    if (dst && USER_SKILLS.test(dst)) bad.push(m[0].trim());
  }
  for (const c of joined.matchAll(CD_THEN)) {
    if (!USER_SKILLS.test(c[1])) continue;
    for (const m of c[2].matchAll(COPY)) {
      const dst = destination(m[1], m[2]);
      if (dst && RELATIVE.test(dst)) bad.push(c[0].trim());
    }
  }
  return bad;
}

// Code in a script that names the user-level skills folder: on one line, a home token (homedir(), expanduser(,
// process.env.HOME, os.environ, Path.home()) and the folder, either as `.claude/skills` or as the quoted path parts
// '.claude' and 'skills' (path.join(process.env.HOME, '.claude', 'skills'), Path.home() / '.claude' / 'skills';
// review PR6-R-11). Scripts under the definition trees must not address that folder at all (review PR6-R-4); none
// does today (check-skill-deploy.js lives in scripts/, which is not a definition tree).
// Each check is a separate single pass over the line: fixed alternatives with no `[^\n]*` between them, so a long
// line of repeated tokens cannot make it backtrack (review PR6-R-10; timed below).
const HOME_TOKEN = /homedir\(\)|expanduser\(|process\.env\.HOME\b|os\.environ|Path\.home\(\)/;
const QUOTED_CLAUDE = /['"`]\.claude['"`]/;
const QUOTED_SKILLS = /['"`]skills['"`]/;
const namesUserSkills = l => HOME_TOKEN.test(l)
  && (l.includes('.claude/skills') || (QUOTED_CLAUDE.test(l) && QUOTED_SKILLS.test(l)));
const codeUserSkills = text => text.split('\n').filter(namesUserSkills).map(l => l.trim());

// Reports and logs are dated history, not definitions: SKILL-EVAL.md, <agent>-EVAL.md, *-REFINE-LOG.md.
const REPORT = /(?:^|-)EVAL\.md$|REFINE-LOG\.md$/;
// Scripts: no exclusion. No script under these trees, test files included, holds a deploy form today.
const SCRIPT = /\.(?:sh|js|cjs|mjs|ts|cts|mts|py)$/;
const DEFINITION_DIRS = ['skills', '.claude/agents', '.claude/skills', 'packs', 'infra/hermes-agent/skills'];

function walk(dir, keep, out = []) {
  if (!fs.existsSync(dir)) return out;
  for (const e of fs.readdirSync(dir, { withFileTypes: true })) {
    const p = path.join(dir, e.name);
    if (e.isDirectory()) walk(p, keep, out);
    else if (keep(e.name)) out.push(p);
  }
  return out;
}
const definitionFiles = (root = REPO) => DEFINITION_DIRS.flatMap(d => walk(path.join(root, d), n => n.endsWith('.md') && !REPORT.test(n)));
const scriptFiles = (root = REPO) => DEFINITION_DIRS.flatMap(d => walk(path.join(root, d), n => SCRIPT.test(n)));

// Every copy into the user-level skills folder in the definitions and their scripts under `root`, as "file: command".
const deploySteps = (root = REPO) => [
  ...definitionFiles(root).flatMap(f => userSkillsCopies(fs.readFileSync(f, 'utf8')).map(c => `${path.relative(root, f)}: ${c}`)),
  ...scriptFiles(root).flatMap(f => {
    const text = fs.readFileSync(f, 'utf8');
    return [...userSkillsCopies(text), ...codeUserSkills(text)].map(c => `${path.relative(root, f)}: ${c}`);
  }),
];

module.exports = { userSkillsCopies, definitionFiles, scriptFiles, deploySteps };
if (require.main !== module) return;

let ok = true;
function test(label, fn) {
  try { fn(); console.log(`PASS ${label}`); }
  catch (e) { console.error(`FAIL ${label}: ${e.message}`); ok = false; }
}
const read = f => fs.readFileSync(path.join(REPO, f), 'utf8');
const lines = (text, re) => text.split('\n').map(l => l.replace(/\*\*/g, '')).filter(l => re.test(l));

test('the matcher flags the three original deploy steps and their variants, and nothing that only reads', () => {
  const flagged = [
    '   - score > baseline + 2% → **KEEP**. Sync to runtime: `cp -r skills/<skill-name> ~/.claude/skills/`',   // skill-refine:67 at fce8542
    '   - score > baseline + 2% → KEEP. Sync: `cp -r skills/<skill-name> ~/.claude/skills/`',                  // skill-refine-agent:144
    '    cp -r skills/<skill-name> ~/.claude/skills/',                                                          // skill-adapt:86
    'cp -R skills/<name>/. ~/.claude/skills/<name>/', 'cp -R skills/x ~/.claude/skills', 'rsync -a skills/x/ ~/.claude/skills/x/',
    'cp -r skills/x "$HOME"/.claude/skills/', 'cp -r skills/x "$HOME/.claude/skills/"', 'cp -r skills/x ${HOME}/.claude/skills',
    'cp -r skills/x /Users/someone/.claude/skills/', 'cp -r skills/x "${CLAUDE_CONFIG_DIR:-$HOME/.claude}/skills/"',
    'ln -s "$PWD/skills/x" ~/.claude/skills/x', 'cp -r skills/x 2>/dev/null ~/.claude/skills/', 'cp -r skills/x \\\n  ~/.claude/skills/',
    // Destination first, and a cd into the folder before the copy (review PR6-R-5).
    'cp -t ~/.claude/skills/ -R skills/x', 'cp -Rt ~/.claude/skills skills/x', 'cp --target-directory=$HOME/.claude/skills -R skills/x',
    'mv --target-directory ~/.claude/skills skills/x', 'cd ~/.claude/skills && cp -R /repo/skills/x .',
    'cd "$HOME/.claude/skills"; rsync -a /repo/skills/x .',
  ];
  for (const s of flagged) assert.strictEqual(userSkillsCopies(s).length, 1, `not flagged: ${s}`);
  const clean = [
    'cp -R skills/<skill-name>/. evals/<skill-name>/adapt-backup-$TS/', 'cp ~/.claude/skills/x/SKILL.md evals/x/installed.md',
    'diff -rq skills/x ~/.claude/skills/x', 'ls ~/.claude/skills/', 'read from `~/.claude/skills/<name>/`',
    'cp .claude/agents/x.md evals/agents/x/refine/x.md.baseline', 'cp -r skills/x .claude/skills/',
    'cp -t evals/x/ skills/x/SKILL.md', 'rsync -t skills/x/ evals/x/', 'cd ~/.claude/skills && ls',
    'cd ~/.claude/skills && cp x/SKILL.md /tmp/x.md',
  ];
  for (const s of clean) assert.deepStrictEqual(userSkillsCopies(s), [], `flagged: ${s}`);
});

test('no definition under skills/, .claude/agents/, .claude/skills/, packs/ or the Hermes skills copies a skill into ~/.claude/skills (P0-08)', () => {
  assert.ok(definitionFiles().length > 0, 'no definitions found');
  assert.deepStrictEqual(deploySteps(), []);
});

// Review PR6-R-4: skill-refine's Lever E edits a skill's scripts, so the scan reads scripts too. A mutant tree in a
// fresh temp folder: one deploying script per language, a clean one reading the home settings file, a clean skill.
test('the scan reads .sh, .js, .mjs and .py files under the definition trees and catches a script deploy (review PR6-R-4)', () => {
  const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'staged-deploys-test-'));
  try {
    const put = (rel, text) => { fs.mkdirSync(path.dirname(path.join(tmp, rel)), { recursive: true }); fs.writeFileSync(path.join(tmp, rel), text); };
    put('skills/demo/SKILL.md', '---\nname: demo\n---\nStage the result; the owner deploys it.\n');
    put('skills/demo/scripts/deploy.sh', '#!/bin/sh\ncp -R skills/demo ~/.claude/skills/\n');
    put('skills/demo/scripts/deploy.js', "fs.cpSync('skills/demo', path.join(os.homedir(), '.claude', 'skills', 'demo'), { recursive: true });\n");
    put('skills/demo/scripts/deploy.mjs', 'await $`rsync -a skills/demo/ ~/.claude/skills/demo/`;\n');   // zx-style shell template
    put('.claude/agents/demo-agent/deploy.py', "shutil.copytree('skills/demo', os.path.expanduser('~/.claude/skills/demo'))\n");
    put('skills/demo/scripts/read-settings.js', "const s = readFile(os.homedir(), '.claude', 'settings.json');\n");
    put('skills/demo/scripts/notes.txt', 'cp -R skills/demo ~/.claude/skills/\n');   // not a script: not read
    // Review PR6-R-11: the folder named as separate path parts beside a home token (N4-N6), and .ts/.cjs/.mts/.cts (N9, N10).
    put('skills/demo/scripts/n4.js', "fs.cpSync('skills/demo', path.join(process.env.HOME, '.claude', 'skills', n), { recursive: true });\n");
    put('skills/demo/scripts/n5.py', "shutil.copytree('skills/demo', os.path.join(os.path.expanduser('~'), '.claude', 'skills', n))\n");
    put('skills/demo/scripts/n6.py', "shutil.copytree('skills/demo', Path.home() / '.claude' / 'skills' / n)\n");
    put('skills/demo/scripts/n9.ts', "fs.cpSync('skills/demo', path.join(os.homedir(), '.claude', 'skills', n), { recursive: true });\n");
    put('skills/demo/scripts/n10.cjs', "fs.cpSync('skills/demo', path.join(os.homedir(), '.claude/skills', n), { recursive: true });\n");
    put('skills/demo/scripts/n11.mts', "await $`cp -R skills/demo ~/.claude/skills/`;\n");
    put('skills/demo/scripts/n12.cts', "fs.cpSync('skills/demo', path.join(os.homedir(), '.claude', 'skills', n));\n");
    // Clean: a home token with another .claude file, and the project's own skills folder.
    put('skills/demo/scripts/clean.py', "p = os.path.join(os.path.expanduser('~'), '.claude', 'settings.json')\n");
    put('skills/demo/scripts/clean.ts', "const d = path.join(REPO, '.claude', 'skills', n);\n");
    const found = deploySteps(tmp).map(x => x.split(':')[0]).sort();
    assert.deepStrictEqual(found, ['.claude/agents/demo-agent/deploy.py', 'skills/demo/scripts/deploy.js',
      'skills/demo/scripts/deploy.mjs', 'skills/demo/scripts/deploy.sh', 'skills/demo/scripts/n10.cjs',
      'skills/demo/scripts/n11.mts', 'skills/demo/scripts/n12.cts', 'skills/demo/scripts/n4.js',
      'skills/demo/scripts/n5.py', 'skills/demo/scripts/n6.py', 'skills/demo/scripts/n9.ts']);
  } finally {
    fs.rmSync(tmp, { recursive: true, force: true });
  }
});

// Review PR6-R-10: the code-path check must be linear. One 1 MB line of a repeated home token, with no skills path
// (the backtracking case), per token. The bound is generous; the measured times are printed.
test('the code-path check stays linear on a 1 MB line of repeated home tokens (review PR6-R-10)', () => {
  const slow = [];
  for (const token of ['homedir() ', 'os.environ ', 'process.env.HOME ', 'expanduser( ', 'Path.home() ', "homedir() '.claude' "]) {
    const line = token.repeat(Math.ceil((1 << 20) / token.length)).slice(0, 1 << 20);
    const t0 = process.hrtime.bigint();
    const hits = codeUserSkills(line);
    const ms = Number(process.hrtime.bigint() - t0) / 1e6;
    console.log(`  1 MB of ${JSON.stringify(token.trim())}: ${ms.toFixed(1)} ms, ${hits.length} hit(s)`);
    assert.deepStrictEqual(hits, [], token);
    if (ms >= 1000) slow.push(`${token.trim()}: ${ms.toFixed(0)} ms`);
  }
  assert.deepStrictEqual(slow, []);
});

// The three steps that deployed, and what they say now.
const STAGED = 'staged: record in SKILL-REFINE-LOG.md; deployment waits for owner approval';
for (const file of ['skills/skill-refine/SKILL.md', '.claude/agents/skill-refine-agent.md']) {
  test(`${file}: the KEEP step stages the result and waits for owner approval (P0-08)`, () => {
    const keep = lines(read(file), /score > baseline \+ 2%/);
    assert.ok(keep.length >= 1, 'no keep line');
    for (const l of keep) assert.ok(l.includes(STAGED), `keep line does not stage: ${l.trim()}`);
  });
  test(`${file}: a neutral KEEP is staged too, and no line syncs or deploys (P0-08)`, () => {
    const text = read(file);
    for (const l of lines(text, /baseline − 5% ≤ score ≤ baseline \+ 2%/)) assert.match(l, /if it did, KEEP \(staged as above\)/i, l.trim());
    assert.deepStrictEqual(lines(text, /\bsync(?:s|ed|ing)?\b/i).filter(l => !/install\.sh/.test(l)), []);
  });
}

test('skills/skill-adapt/SKILL.md: step 10 stages the result and waits for owner approval (P0-08)', () => {
  const text = read('skills/skill-adapt/SKILL.md');
  const step = text.split('\n').find(l => /^10\. /.test(l)) || '';
  assert.match(step.replace(/\*\*/g, ''), /^10\. Stage, do not deploy\b/, `step 10: ${step}`);
  assert.ok(step.includes('deployment waits for owner approval'), `step 10: ${step}`);
  assert.ok(!/sync to runtime|can use it immediately/i.test(text), 'the runtime sync wording is still there');
});

test('skill-refine, skill-refine-agent and skill-adapt each carry a rule against deploying themselves (P0-08)', () => {
  for (const file of ['skills/skill-refine/SKILL.md', '.claude/agents/skill-refine-agent.md', 'skills/skill-adapt/SKILL.md']) {
    assert.match(read(file), /Never (?:copy|deploy)[^\n]*~\/\.claude\/skills\/[^\n]*owner/i, file);
  }
});

// The owner instruction: CLAUDE.md's Always bullet (V2-RS-9) and the section install.sh writes into targets.
const OWNER_DEFINITION = "'Owner deploys' means the owner runs the deploy command or explicitly approves it";
test('CLAUDE.md: the deploy bullet says the owner deploys, defines it, and says the three flows stage (P0-08, V2-RS-9)', () => {
  const bullet = read('CLAUDE.md').split('\n').find(l => l.startsWith('- After a skill change merges to main')) || '';
  for (const s of ['the owner deploys it (`cp -R skills/<name>/. ~/.claude/skills/<name>/`) and runs `node scripts/check-skill-deploy.js`',
    "Claude Code loads skills from `~/.claude/skills/`, not from this repo's `skills/`, so its skill loading does not see an undeployed change",
    `${OWNER_DEFINITION} (for example at the P0-07 ask prompt)`,
    'skill-adapt, skill-refine and skill-refine-agent stage their result and never deploy it themselves']) {
    assert.ok(bullet.includes(s), `missing: ${s}`);
  }
  assert.ok(!/sync their own result/.test(read('CLAUDE.md')), 'the old self-sync sentence is still there');
});

test('install.sh: the CLAUDE.md section it writes into targets carries the same deploy instruction (P0-08, R-B-11)', () => {
  // Between the markers, so uninstall.sh's marker-based removal takes the new line with the section.
  const text = read('install.sh');
  const start = text.indexOf('\n# >>> skill-builder >>>\n');
  const end = text.indexOf('\n# <<< skill-builder <<<\n', start);
  assert.ok(start !== -1 && end > start, 'pipeline section markers not found');
  const section = text.slice(start, end);
  for (const s of ['the owner deploys it (`cp -R skills/<name>/. ~/.claude/skills/<name>/`)',
    // review PR6-R-7: macOS folder files ignored, and the only-installed case explained
    // diff prints the expanded home path, so the text names the side, not a literal "Only in ~/…" line
    '`diff -rq -x .DS_Store skills/<name> ~/.claude/skills/<name>`', 'an "Only in" line for the `~/.claude/skills/<name>` side',
    "Claude Code loads skills from `~/.claude/skills/`, not from this project's `skills/`",
    OWNER_DEFINITION, 'skill-adapt, skill-refine and skill-refine-agent stage their result and never deploy it themselves']) {
    assert.ok(section.includes(s), `missing: ${s}`);
  }
});

if (!ok) process.exit(1);
console.log('\nAll staged-deploys tests passed.');
