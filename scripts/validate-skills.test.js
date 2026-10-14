#!/usr/bin/env node
// scripts/validate-skills.test.js — tests for the skill-reference resolver in
// scripts/validate-skills.js. Builds throwaway fixture trees under os.tmpdir()
// and calls the exported pure function; the real-repo test runs it on this repo.
'use strict';
const assert = require('assert');
const fs = require('fs');
const os = require('os');
const path = require('path');

const { findUnresolvedSkillRefs, EXTERNAL_SKILLS } = require('./validate-skills');

const REPO = path.join(__dirname, '..');

let ok = true;
function test(label, fn) {
  try { fn(); console.log(`PASS ${label}`); }
  catch (e) { console.error(`FAIL ${label}: ${e.message}`); ok = false; }
}

// Fixture: skills/<name>/SKILL.md (+ optional extra files) and agents/<name>.md.
function fixture({ skills = {}, agents = {} }) {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'validate-skills-'));
  for (const [name, files] of Object.entries(skills)) {
    for (const [file, body] of Object.entries(files)) {
      const p = path.join(root, 'skills', name, file);
      fs.mkdirSync(path.dirname(p), { recursive: true });
      fs.writeFileSync(p, body);
    }
  }
  fs.mkdirSync(path.join(root, 'agents'), { recursive: true });
  for (const [name, body] of Object.entries(agents)) {
    fs.writeFileSync(path.join(root, 'agents', `${name}.md`), body);
  }
  return {
    root,
    opts: { skillsDir: path.join(root, 'skills'), agentDirs: [path.join(root, 'agents')] },
  };
}

test('flags a backticked invocation of a skill that does not exist', () => {
  const { opts } = fixture({ skills: { 'skill-scout': { 'SKILL.md': 'If nothing scores > 5, invoke `write-a-skill`.\n' } } });
  const refs = findUnresolvedSkillRefs(opts);
  assert.strictEqual(refs.length, 1);
  assert.strictEqual(refs[0].name, 'write-a-skill');
  assert.match(refs[0].location, /skill-scout[\\/]SKILL\.md:1$/);
});

test('resolves references to existing skills and agents', () => {
  const { opts } = fixture({
    skills: {
      'skill-audit': { 'SKILL.md': 'x\n' },
      'skill-scout': { 'SKILL.md': 'Then run `skill-audit`, or dispatch the `skill-eval-agent` agent.\n' },
    },
    agents: { 'skill-eval-agent': 'agent body\n' },
  });
  assert.deepStrictEqual(findUnresolvedSkillRefs(opts), []);
});

test('scans supporting markdown files, not just SKILL.md', () => {
  const { opts } = fixture({ skills: { 'skill-refine': { 'SKILL.md': 'x\n', 'REFERENCE.md': 'a\nb\nrecommend `ghost-skill`\n' } } });
  const refs = findUnresolvedSkillRefs(opts);
  assert.strictEqual(refs.length, 1);
  assert.match(refs[0].location, /REFERENCE\.md:3$/);
});

test('scans agent definitions', () => {
  const { opts } = fixture({ agents: { 'skill-refine-agent': 'Recommend `missing-skill` and exit.\n' } });
  assert.deepStrictEqual(findUnresolvedSkillRefs(opts).map(r => r.name), ['missing-skill']);
});

test('ignores generated eval reports and refine logs (historical artifacts)', () => {
  const { opts } = fixture({ skills: { 'skill-adapt': { 'SKILL.md': 'x\n', 'SKILL-EVAL.md': 'route to `write-a-skill`\n', 'SKILL-REFINE-LOG.md': 'use `old-skill`\n' } } });
  assert.deepStrictEqual(findUnresolvedSkillRefs(opts), []);
});

test('namespaced plugin skills must be declared external', () => {
  const { opts } = fixture({ skills: { 'skill-scout': { 'SKILL.md': 'invoke `superpowers:writing-skills`, or use `other:undeclared-skill`.\n' } } });
  const refs = findUnresolvedSkillRefs({ ...opts, external: ['superpowers:writing-skills'] });
  assert.deepStrictEqual(refs.map(r => r.name), ['other:undeclared-skill']);
});

test('only invocation-shaped mentions count: plain backticked paths or flags do not', () => {
  const { opts } = fixture({ skills: { 's-a': { 'SKILL.md': 'The file `project-context.json` and the flag `--max-iterations` and `dry-run` mode.\n' } } });
  assert.deepStrictEqual(findUnresolvedSkillRefs(opts), []);
});

test('the declared external list names the D1 generate path', () => {
  assert.ok(EXTERNAL_SKILLS.includes('superpowers:writing-skills'));
});

test('real repo: no unresolved skill references in skills/ or .claude/agents/', () => {
  const refs = findUnresolvedSkillRefs({
    skillsDir: path.join(REPO, 'skills'),
    agentDirs: [path.join(REPO, '.claude', 'agents')],
    knownSkillDirs: [path.join(REPO, '.claude', 'skills')],
  });
  assert.deepStrictEqual(refs, [], refs.map(r => `${r.name} @ ${r.location}`).join(', '));
});

if (!ok) process.exit(1);
console.log('\nvalidate-skills.test.js: all tests passed');
