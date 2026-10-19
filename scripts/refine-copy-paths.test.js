#!/usr/bin/env node
// scripts/refine-copy-paths.test.js — where skill-refine, agent-refine and skill-adapt keep their safety copies
// (E13, PR #4 triage; the E8 class). They used to sit in the definition's own folder (`skills/<name>/SKILL.md.baseline`,
// `….pre-iter-N`, `.claude/agents/<name>.md.baseline`) or beside it (`skills/<name>-backup-<date>/`, which install.sh
// step 2 syncs into ~/.claude/skills as a second copy of the skill). None was ignored here, and skill-refine-agent's
// keep step (`cp -r skills/<name> ~/.claude/skills/`) carried them into the installed skill. They now live under
// evals/<name>/, which is ignored here (evals/.gitignore) and in target projects (install.sh ignores evals/).
'use strict';
const assert = require('assert');
const fs = require('fs');
const path = require('path');
const { spawnSync } = require('child_process');

const REPO = path.join(__dirname, '..');

let ok = true;
function test(label, fn) {
  try { fn(); console.log(`PASS ${label}`); }
  catch (e) { console.error(`FAIL ${label}: ${e.message}`); ok = false; }
}

const DOCS = [
  'skills/skill-refine/SKILL.md', '.claude/agents/skill-refine-agent.md',
  'skills/agent-refine/SKILL.md', '.claude/agents/agent-refine-agent.md',
  'skills/skill-adapt/SKILL.md',
];

// Path-like tokens naming a refine/adapt safety copy.
const copyTokens = text => (text.match(/[^\s`'"()\[\]]*(?:\.baseline|\.pre-iter-[^\s`'"()\[\]]*|-backup-[^\s`'"()\[\]]*)/g) || [])
  .filter(t => t.includes('/'));   // a path; a bare name in prose ("never overwrite SKILL.md.baseline") is not one

// `cp [-r|-R] <src> <dst>` commands in the text.
const cps = text => [...text.matchAll(/\bcp(?: -[rR])? ([^\s`]+) ([^\s`]+)/g)].map(m => ({ src: m[1], dst: m[2], at: m.index }));

for (const file of DOCS) {
  const text = fs.readFileSync(path.join(REPO, file), 'utf8');

  test(`${file}: every safety-copy path is under evals/`, () => {
    const tokens = copyTokens(text);
    assert.ok(tokens.length > 0, 'no safety-copy path found');
    assert.deepStrictEqual(tokens.filter(t => !t.startsWith('evals/')), []);
  });

  test(`${file}: each copy into evals/ is preceded by a mkdir -p of its folder`, () => {
    const made = cps(text).filter(c => c.dst.startsWith('evals/'));
    assert.ok(made.length > 0, 'no copy into evals/');
    for (const c of made) {
      const dir = path.posix.dirname(c.dst);
      const mk = text.indexOf(`mkdir -p ${dir}`);
      assert.ok(mk !== -1 && mk < c.at, `no "mkdir -p ${dir}" before: cp ${c.src} ${c.dst}`);
    }
  });

  test(`${file}: every restore reads a copy this document creates`, () => {
    const all = cps(text);
    const created = new Set(all.filter(c => c.dst.startsWith('evals/')).map(c => c.dst));
    for (const r of all.filter(c => c.src.startsWith('evals/'))) assert.ok(created.has(r.src), `restores from ${r.src}, never created`);
  });
}

for (const sample of ['evals/demo/refine/SKILL.md.baseline', 'evals/demo/refine/SKILL.md.pre-iter-3',
  'evals/agents/demo/refine/demo.md.baseline', 'evals/agents/demo/refine/demo.md.pre-iter-3',
  'evals/demo/adapt-backup-20261019-120000/SKILL.md']) {
  test(`${sample} is gitignored in this repo`, () => {
    assert.strictEqual(spawnSync('git', ['check-ignore', '-q', sample], { cwd: REPO }).status, 0);
  });
}

if (!ok) process.exit(1);
console.log('\nAll refine-copy-paths tests passed.');
