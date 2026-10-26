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
const path = require('path');

const REPO = path.join(__dirname, '..');

// A copy command's arguments up to a shell separator or a closing backtick.
const COPY = /\b(?:cp|rsync|install|ln|mv|ditto)\b((?:[ \t]+[^\s`;|&]+)+)/g;
const REDIRECT = /^(?:\d*|&)[<>]/;   // 2>/dev/null, >log; a bare "2>" also takes the next operand
// The user-level skills folder: home by any spelling, or the config folder variable.
const USER_SKILLS = /^["']?(?:~|\$HOME|\$\{HOME\}|\/Users\/[^/]+|\/home\/[^/]+|\/root)["']?\/\.claude\/skills(?:\/|["']?$)|^["']?\$\{?CLAUDE_CONFIG_DIR\b[^}/]*(?:\}|[^}]*\})?["']?\/skills(?:\/|["']?$)/;

function operands(args) {
  const out = [];
  const words = args.trim().split(/[ \t]+/);
  for (let i = 0; i < words.length; i++) {
    const w = words[i];
    if (REDIRECT.test(w)) { if (/[<>]$/.test(w)) i++; continue; }
    if (!w.startsWith('-')) out.push(w);
  }
  return out;
}

// The copy commands in `text` whose destination is the user-level skills folder.
function userSkillsCopies(text) {
  const joined = text.replace(/\\\r?\n[ \t]*/g, ' ');   // shell line continuations joined
  const bad = [];
  for (const m of joined.matchAll(COPY)) {
    const ops = operands(m[1]);
    if (ops.length < 2) continue;
    if (USER_SKILLS.test(ops[ops.length - 1])) bad.push(m[0].trim());
  }
  return bad;
}

// Reports and logs are dated history, not definitions: SKILL-EVAL.md, <agent>-EVAL.md, *-REFINE-LOG.md.
const REPORT = /(?:^|-)EVAL\.md$|REFINE-LOG\.md$/;
const DEFINITION_DIRS = ['skills', '.claude/agents', '.claude/skills', 'packs', 'infra/hermes-agent/skills'];

function mdFiles(dir, out = []) {
  if (!fs.existsSync(dir)) return out;
  for (const e of fs.readdirSync(dir, { withFileTypes: true })) {
    const p = path.join(dir, e.name);
    if (e.isDirectory()) mdFiles(p, out);
    else if (e.name.endsWith('.md') && !REPORT.test(e.name)) out.push(p);
  }
  return out;
}
const definitionFiles = (root = REPO) => DEFINITION_DIRS.flatMap(d => mdFiles(path.join(root, d)));

// Every copy into the user-level skills folder in the definitions under `root`, as "file: command".
const deploySteps = (root = REPO) => definitionFiles(root)
  .flatMap(f => userSkillsCopies(fs.readFileSync(f, 'utf8')).map(c => `${path.relative(root, f)}: ${c}`));

module.exports = { userSkillsCopies, definitionFiles, deploySteps };
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
  ];
  for (const s of flagged) assert.strictEqual(userSkillsCopies(s).length, 1, `not flagged: ${s}`);
  const clean = [
    'cp -R skills/<skill-name>/. evals/<skill-name>/adapt-backup-$TS/', 'cp ~/.claude/skills/x/SKILL.md evals/x/installed.md',
    'diff -rq skills/x ~/.claude/skills/x', 'ls ~/.claude/skills/', 'read from `~/.claude/skills/<name>/`',
    'cp .claude/agents/x.md evals/agents/x/refine/x.md.baseline', 'cp -r skills/x .claude/skills/',
  ];
  for (const s of clean) assert.deepStrictEqual(userSkillsCopies(s), [], `flagged: ${s}`);
});

test('no definition under skills/, .claude/agents/, .claude/skills/, packs/ or the Hermes skills copies a skill into ~/.claude/skills (P0-08)', () => {
  assert.ok(definitionFiles().length > 0, 'no definitions found');
  assert.deepStrictEqual(deploySteps(), []);
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
    "Claude Code loads skills from `~/.claude/skills/`, not from this project's `skills/`",
    OWNER_DEFINITION, 'skill-adapt, skill-refine and skill-refine-agent stage their result and never deploy it themselves']) {
    assert.ok(section.includes(s), `missing: ${s}`);
  }
});

if (!ok) process.exit(1);
console.log('\nAll staged-deploys tests passed.');
