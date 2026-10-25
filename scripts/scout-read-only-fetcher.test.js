#!/usr/bin/env node
// scripts/scout-read-only-fetcher.test.js — P0-05 acceptance on the definitions: skill-scout-agent is a read-only
// fetcher (exactly Read, WebFetch, WebSearch: no Write, Bash, Edit or Agent), its output contract names the same closed
// key set the scorer enforces, and skill-scout runs the scorer in agent-output mode from a scratch file it writes
// with the Write tool. The scorer's own behaviour is tested in scripts/score-candidates.test.js.
// Record: docs/evaluations/2026-10-25-p0-05-scout-read-only-fetcher.md.
'use strict';
const assert = require('assert');
const fs = require('fs');
const path = require('path');

const REPO = path.join(__dirname, '..');
const AGENT = path.join(REPO, '.claude', 'agents', 'skill-scout-agent.md');
const SKILL = path.join(REPO, 'skills', 'skill-scout', 'SKILL.md');
const scorer = require(path.join(REPO, 'skills', 'skill-scout', 'scripts', 'score-candidates.js'));

let ok = true;
function test(label, fn) {
  try { fn(); console.log(`PASS ${label}`); }
  catch (e) { console.error(`FAIL ${label}: ${e.message}`); ok = false; }
}

const read = p => fs.readFileSync(p, 'utf8');
const frontmatter = text => (text.match(/^---\r?\n([\s\S]*?)\r?\n---/) || [, ''])[1];
// "tools: [\"Read\", \"WebFetch\"]" | "tools: Read, WebFetch" → ['Read', 'WebFetch']
function tools(text) {
  const line = frontmatter(text).split(/\r?\n/).find(l => l.startsWith('tools:'));
  return line ? line.slice(6).replace(/[[\]"']/g, ' ').split(',').map(s => s.trim()).filter(Boolean) : null;
}
const body = text => text.replace(/^---\r?\n[\s\S]*?\r?\n---\r?\n/, '');

test('agent: tools are exactly Read, WebFetch, WebSearch', () => {
  assert.deepStrictEqual(tools(read(AGENT)), ['Read', 'WebFetch', 'WebSearch']);
});

test('agent: no /tmp write and no scorer call left in the definition', () => {
  const text = read(AGENT);
  assert.ok(!text.includes('/tmp'), '/tmp');
  assert.ok(!text.includes('score-candidates'), 'score-candidates');
});

test('agent: the output contract names every key of the closed set, in backticks', () => {
  const text = body(read(AGENT));
  assert.ok(scorer.AGENT_CANDIDATE_KEYS.length >= 10, 'scorer exports its key set');
  for (const k of scorer.AGENT_CANDIDATE_KEYS) assert.ok(text.includes(`\`${k}\``), `agent names \`${k}\``);
  assert.ok(text.includes(String(scorer.DESCRIPTION_CAP)), 'agent states the description cap');
});

test('scorer: the description cap is the Agent Skills spec maximum (1024) and the excerpt cap is 100', () => {
  assert.strictEqual(scorer.DESCRIPTION_CAP, 1024);
  assert.strictEqual(scorer.EXCERPT_CAP, 100);
  assert.ok(!scorer.AGENT_CANDIDATE_KEYS.includes('skill_md_content'));
});

test('skill-scout: dispatches the agent and scores its output in agent-output mode from a Write-tool scratch file', () => {
  const text = body(read(SKILL));
  assert.ok(/dispatch\s+`skill-scout-agent`/i.test(text), 'dispatches skill-scout-agent');
  assert.ok(text.includes('score-candidates.js --agent-output'), 'runs the strict mode');
  assert.ok(/Write tool/.test(text), 'writes the scratch file with the Write tool');
  assert.ok(!text.includes('/tmp'), 'no /tmp instruction');
  assert.ok(!/WebFetch the raw `SKILL\.md`/.test(text), 'the session no longer fetches candidate bodies');
});

// Background security review of 908764b (parser differential): the shortlist is built from what the scorer
// validated, never from the agent's raw reply (which may differ, e.g. a duplicate key's first value).
test('skill-scout: the shortlist comes only from the scorer\'s validated stdout', () => {
  const text = body(read(SKILL));
  assert.ok(/only from the scorer's (?:validated )?(?:stdout|output)/i.test(text), 'states the source of the shortlist');
  assert.ok(/never from the agent's (?:raw )?reply/i.test(text), 'forbids the raw reply as a source');
});

if (!ok) process.exit(1);
console.log('\nscout-read-only-fetcher.test.js: all tests passed');
