#!/usr/bin/env node
// scripts/refine-copy-paths.test.js — where skill-refine, agent-refine and skill-adapt keep their safety copies
// (E13, PR #4 triage; the E8 class). They used to sit in the definition's own folder (`skills/<name>/SKILL.md.baseline`,
// `….pre-iter-N`, `.claude/agents/<name>.md.baseline`) or beside it (`skills/<name>-backup-<date>/`, which install.sh
// step 2 syncs into ~/.claude/skills as a second copy of the skill). None was ignored here, and skill-refine-agent's
// keep step (`cp -r skills/<name> ~/.claude/skills/`) carried them into the installed skill. They now live under
// evals/<name>/, which is ignored here (evals/.gitignore) and in target projects (install.sh ignores evals/).
//
// Every check reads the paths from the documents themselves (review N1): a copy written anywhere git does not
// ignore, a mkdir of the wrong folder, a missing or reversed restore, or an unguarded baseline fails.
// Since E16 the skill flows copy the whole skill folder per iteration (`…/refine/pre-iter-N/`) and restore the one
// edited file from it (`…/pre-iter-N/<file>`); refine-snapshot.test.js runs those commands.
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
  { file: 'skills/skill-refine/SKILL.md', restoreTo: 'skills/<skill-name>/<file>' },
  { file: '.claude/agents/skill-refine-agent.md', restoreTo: 'skills/<skill-name>/<file>' },
  { file: '.claude/agents/skill-guardian.md', restoreTo: 'skills/<skill-name>/<file>' },
  { file: 'skills/agent-refine/SKILL.md', restoreTo: '.claude/agents/<name>.md' },
  { file: '.claude/agents/agent-refine-agent.md', restoreTo: '.claude/agents/<agent-name>.md' },
  { file: 'skills/skill-adapt/SKILL.md' },
];

// Path-like tokens naming a refine/adapt safety copy; a bare name in prose ("never overwrite SKILL.md.baseline") is not one.
const copyTokens = text => (text.match(/[^\s`'"()\[\]]*(?:\.baseline|[./]pre-iter-[^\s`'"()\[\]]*|-backup-[^\s`'"()\[\]]*)/g) || [])
  .filter(t => t.includes('/'));

// `cp [-r|-R] <src> <dst>` commands in the text.
// A `;` ends a command: the skill flows' restore runs inside `if …; then cp …; else …; fi`. Paths may be quoted
// (the skill flows quote theirs, E16 review Q3).
const cps = text => [...text.matchAll(/\bcp(?: -[rR])? "?([^\s`";]+)"? "?([^\s`";]+)"?/g)].map(m => ({ src: m[1], dst: m[2], at: m.index }));

// Placeholders filled in, so git can be asked about a concrete path.
const fill = p => p.replace(/<skill-name>|<agent-name>|<name>/g, 'demo').replace(/-N\b/g, '-3').replace(/\$TS\b/g, '20261019-120000');

for (const { file, restoreTo } of DOCS) {
  const text = fs.readFileSync(path.join(REPO, file), 'utf8');
  const all = cps(text);
  const made = all.filter(c => c.dst.startsWith('evals/'));

  test(`${file}: every safety-copy path is under evals/`, () => {
    const tokens = copyTokens(text);
    assert.ok(tokens.length > 0, 'no safety-copy path found');
    assert.deepStrictEqual(tokens.filter(t => !t.startsWith('evals/')), []);
  });

  test(`${file}: every copy it writes under evals/ is gitignored here`, () => {
    assert.ok(made.length > 0, 'no copy into evals/');
    for (const c of made) {
      const target = fill(c.dst.endsWith('/') ? c.dst + 'SKILL.md' : c.dst);
      assert.strictEqual(spawnSync('git', ['check-ignore', '-q', target], { cwd: REPO }).status, 0, `${c.dst} → ${target} is not ignored`);
    }
  });

  test(`${file}: each copy into evals/ is preceded by a mkdir -p of exactly its folder`, () => {
    for (const c of made) {
      const dir = c.dst.endsWith('/') ? c.dst.slice(0, -1) : path.posix.dirname(c.dst);
      const re = new RegExp(`mkdir -p "?${dir.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}"?(?=[\\s\`]|$)`, 'm');
      const mk = text.search(re);
      assert.ok(mk !== -1 && mk < c.at, `no "mkdir -p ${dir}" before: cp ${c.src} ${c.dst}`);
    }
  });

  test(`${file}: a .baseline copy never overwrites an existing one`, () => {
    for (const c of made.filter(m => m.dst.endsWith('.baseline'))) {
      const guard = `[ -e ${c.dst} ] || `;
      assert.strictEqual(text.slice(c.at - guard.length, c.at), guard, `unguarded: cp ${c.src} ${c.dst}`);
    }
  });

  test(`${file}: every restore reads a copy this document creates`, () => {
    // a file copy, or a file inside a folder copy (a dst ending in /)
    const created = r => made.some(c => c.dst === r || (c.dst.endsWith('/') && r.startsWith(c.dst)));
    // A restore writes back outside evals/. A copy within evals/ (P0-11: evals.json into refine/ for the harvester)
    // is not a restore; it is checked with the other copies into evals/ above.
    const restores = all.filter(c => c.src.startsWith('evals/') && !c.dst.startsWith('evals/'));
    assert.ok(restores.length > 0 || !restoreTo, 'no restore found');
    for (const r of restores) assert.ok(created(r.src), `restores from ${r.src}, never created`);
  });

  if (restoreTo) {
    test(`${file}: the revert step restores ${restoreTo} from its pre-iter copy`, () => {
      const restores = all.filter(c => c.src.startsWith('evals/') && /pre-iter-N(?:\/<file>)?$/.test(c.src));
      assert.ok(restores.length >= 1, 'no restore from a pre-iter copy');
      for (const r of restores) assert.strictEqual(r.dst, restoreTo);
    });
  }
}

test('skill-adapt: the backup folder is stamped to the second and created before the copy', () => {
  const text = fs.readFileSync(path.join(REPO, 'skills/skill-adapt/SKILL.md'), 'utf8');
  assert.match(text, /^\s*TS=\$\(date \+%Y%m%d-%H%M%S\)$/m);
  assert.match(text, /cp -R skills\/<skill-name>\/\. evals\/<skill-name>\/adapt-backup-\$TS\//);   // contents into the new folder: never nests
});

if (!ok) process.exit(1);
console.log('\nAll refine-copy-paths tests passed.');
