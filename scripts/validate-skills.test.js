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
  const { opts } = fixture({ skills: { 'skill-scout': { 'SKILL.md': 'If installed, invoke `superpowers:writing-skills`, or use `other:undeclared-skill`.\n' } } });
  const refs = findUnresolvedSkillRefs({ ...opts, external: ['superpowers:writing-skills'] });
  assert.deepStrictEqual(refs.map(r => r.name), ['other:undeclared-skill']);
});

test('only invocation-shaped mentions count: plain backticked paths or flags do not', () => {
  const { opts } = fixture({ skills: { 's-a': { 'SKILL.md': 'The file `project-context.json` and the flag `--max-iterations` and `dry-run` mode.\n' } } });
  assert.deepStrictEqual(findUnresolvedSkillRefs(opts), []);
});

test('R3: prose after "with" is not a reference (dry-run, kebab-case)', () => {
  const { opts } = fixture({ skills: { 's-b': { 'SKILL.md': 'Run it with `dry-run` mode, with `kebab-case` names.\n' } } });
  assert.deepStrictEqual(findUnresolvedSkillRefs(opts), []);
});

test('R2: the slash-command form `/name` is checked like a bare name', () => {
  const { opts } = fixture({ skills: { 's-c': { 'SKILL.md': 'Then invoke `/write-a-skill`.\n' } } });
  assert.deepStrictEqual(findUnresolvedSkillRefs(opts).map(r => r.name), ['write-a-skill']);
});

test('R4: project-local .claude/skills files are scanned, not only used for resolution', () => {
  const { root, opts } = fixture({ skills: { 's-d': { 'SKILL.md': 'x\n' } } });
  const local = path.join(root, 'local-skills', 'codex-eval');
  fs.mkdirSync(local, { recursive: true });
  fs.writeFileSync(path.join(local, 'SKILL.md'), 'Then invoke `ghost-eval`.\n');
  const refs = findUnresolvedSkillRefs({ ...opts, knownSkillDirs: [path.join(root, 'local-skills')] });
  assert.deepStrictEqual(refs.map(r => r.name), ['ghost-eval']);
});

test('R4: only eval reports and refine logs count as history, not any *-EVAL.md', () => {
  const { opts } = fixture({ skills: { 's-e': { 'SKILL.md': 'x\n', 'PRE-EVAL.md': 'invoke `ghost-pre`\n', 'TEAM-EVAL.md': 'invoke `old-one`\n' } } });
  assert.deepStrictEqual(findUnresolvedSkillRefs(opts).map(r => r.name), ['ghost-pre']);
});

test('agent eval reports beside definitions are history, and are not agents', () => {
  const { opts } = fixture({
    skills: { 's-f': { 'SKILL.md': 'dispatch the `foo-agent-EVAL` agent\n' } },
    agents: { 'foo-agent': 'x\n', 'foo-agent-EVAL': 'invoke `ghost-from-report`\n' },
  });
  assert.deepStrictEqual(findUnresolvedSkillRefs(opts).map(r => r.name), []);
  // the report's own ref is skipped; and "foo-agent-EVAL" is not resolvable as an agent:
  const { opts: o2 } = fixture({ skills: { 's-g': { 'SKILL.md': 'dispatch the `bar-agent-eval` agent\n' } }, agents: { 'bar-agent-EVAL': 'x\n' } });
  assert.deepStrictEqual(findUnresolvedSkillRefs(o2).map(r => r.name), ['bar-agent-eval']);
});

test('optional plugin skills: a reference must state its fallback (portability to target projects)', () => {
  const { opts } = fixture({ skills: { 's-h': { 'SKILL.md': [
    'Build it: invoke `superpowers:writing-skills`.',            // line 1: no fallback nearby -> flagged
    '', '', '',
    'If it is installed, invoke `superpowers:writing-skills`;',  // line 5: fallback stated -> ok
    'otherwise write SKILL.md per the official skills docs.',
    '',
  ].join('\n') } } });
  const refs = findUnresolvedSkillRefs({ ...opts, external: ['superpowers:writing-skills'] });
  assert.deepStrictEqual(refs.map(r => [r.name, r.reason]), [['superpowers:writing-skills', 'no-fallback']]);
  assert.match(refs[0].location, /SKILL\.md:1$/);
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

// ─── Untrusted-content framing (S3 §2.3, P0-03, P0-06) ─────────────────────
const {
  findMissingUntrustedFraming, listUntrustedIntakeFiles,
  UNTRUSTED_INTAKE_FILES, UNTRUSTED_FRAMING_CORES,
} = require('./validate-skills');
const { spawnSync } = require('child_process');

// Copy every intake file of the real tree into a fresh temp root, same relative paths.
function intakeCopy() {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'validate-framing-'));
  const { files } = listUntrustedIntakeFiles(REPO);
  for (const rel of files) {
    const dst = path.join(root, rel);
    fs.mkdirSync(path.dirname(dst), { recursive: true });
    fs.copyFileSync(path.join(REPO, rel), dst);
  }
  return { root, files };
}
function withIntakeCopy(fn) {
  const c = intakeCopy();
  try { fn(c); } finally { fs.rmSync(c.root, { recursive: true, force: true }); }
}

test('framing: the analyst glob finds at least one repo-audit analyst', () => {
  const { analysts } = listUntrustedIntakeFiles(REPO);
  assert.ok(analysts.length >= 1, `analysts: ${analysts.length}`);
  assert.ok(analysts.every(a => /^\.claude\/agents\/repo-audit-[^/]+\.md$/.test(a)), analysts.join(', '));
});

test('framing: the fixed list names the P0-06 readers and repo-audit', () => {
  for (const f of ['skills/skill-scout/SKILL.md', 'skills/repo-audit/SKILL.md', '.claude/agents/skill-synthesizer-agent.md',
    '.claude/skills/codex-eval/SKILL.md', 'skills/skill-audit/SKILL.md', 'skills/agent-audit/SKILL.md']) {
    assert.ok(UNTRUSTED_INTAKE_FILES.includes(f), f);
  }
  assert.strictEqual(UNTRUSTED_FRAMING_CORES.length, 2);
});

test('framing: real repo — every intake file carries both cores in its body', () => {
  const missing = findMissingUntrustedFraming(REPO);
  assert.deepStrictEqual(missing, [], missing.map(m => `${m.file} (${m.reason})`).join(', '));
});

test('framing: a temp copy of the intake files passes', () => {
  withIntakeCopy(({ root }) => assert.deepStrictEqual(findMissingUntrustedFraming(root), []));
});

test('framing: removing the paragraph from one listed file fails on that file', () => {
  withIntakeCopy(({ root }) => {
    const rel = 'skills/skill-adapt/SKILL.md';
    const p = path.join(root, rel);
    let text = fs.readFileSync(p, 'utf8');
    for (const core of UNTRUSTED_FRAMING_CORES) text = text.split(core).join('');
    fs.writeFileSync(p, text);
    const missing = findMissingUntrustedFraming(root);
    assert.deepStrictEqual(missing.map(m => [m.file, m.reason]), [[rel, 'missing-core'], [rel, 'missing-core']]);
  });
});

test('framing: removing it from one analyst fails on that analyst', () => {
  withIntakeCopy(({ root }) => {
    const rel = listUntrustedIntakeFiles(root).analysts[0];
    const p = path.join(root, rel);
    fs.writeFileSync(p, fs.readFileSync(p, 'utf8').split(UNTRUSTED_FRAMING_CORES[1]).join('report it'));
    assert.deepStrictEqual(findMissingUntrustedFraming(root).map(m => [m.file, m.reason]), [[rel, 'missing-core']]);
  });
});

test('framing: a listed file that is missing (renamed) fails', () => {
  withIntakeCopy(({ root }) => {
    const rel = '.claude/skills/codex-eval/SKILL.md';
    fs.renameSync(path.join(root, rel), path.join(root, rel + '.old'));
    assert.deepStrictEqual(findMissingUntrustedFraming(root).map(m => [m.file, m.reason]), [[rel, 'missing-file']]);
  });
});

test('framing: no analyst matching the glob fails (a rename of all analysts is caught)', () => {
  withIntakeCopy(({ root }) => {
    for (const a of listUntrustedIntakeFiles(root).analysts) fs.rmSync(path.join(root, a));
    assert.deepStrictEqual(findMissingUntrustedFraming(root).map(m => m.reason), ['no-analysts']);
  });
});

test('framing: cores only in the frontmatter do not count (body only)', () => {
  withIntakeCopy(({ root }) => {
    const rel = 'skills/agent-scout/SKILL.md';
    const p = path.join(root, rel);
    let text = fs.readFileSync(p, 'utf8');
    for (const core of UNTRUSTED_FRAMING_CORES) text = text.split(core).join('');
    text = text.replace(/^---\n/, `---\nnote: ${UNTRUSTED_FRAMING_CORES.join(' ')}\n`);
    fs.writeFileSync(p, text);
    assert.deepStrictEqual(findMissingUntrustedFraming(root).map(m => m.file), [rel, rel]);
  });
});

test('framing: a core wrapped across lines still counts', () => {
  withIntakeCopy(({ root }) => {
    const p = path.join(root, 'skills/skill-scout/SKILL.md');
    const core = UNTRUSTED_FRAMING_CORES[0];
    const wrapped = core.replace(' never', '\n  never');
    fs.writeFileSync(p, fs.readFileSync(p, 'utf8').split(core).join(wrapped));
    assert.deepStrictEqual(findMissingUntrustedFraming(root), []);
  });
});

test('framing: the CLI reports a missing paragraph and exits non-zero', () => {
  withIntakeCopy(({ root }) => {
    const rel = 'skills/gstack-pattern-audit/SKILL.md';
    const p = path.join(root, rel);
    fs.writeFileSync(p, fs.readFileSync(p, 'utf8').split(UNTRUSTED_FRAMING_CORES[0]).join(''));
    const r = spawnSync(process.execPath, [path.join(__dirname, 'validate-skills.js'), path.join(root, 'skills')], { encoding: 'utf8' });
    assert.notStrictEqual(r.status, 0);
    assert.match(r.stdout, new RegExp(`FAIL  untrusted-content framing missing in ${rel.replace(/[.\/]/g, '\\$&')}`));
    assert.match(r.stdout, /untrusted-content framing: 1 missing/);
  });
});

if (!ok) process.exit(1);
console.log('\nvalidate-skills.test.js: all tests passed');
