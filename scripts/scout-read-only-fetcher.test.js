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
  // Third background review: the reply is in context before validation, so the session must not use it beyond the copy.
  assert.ok(/do not read, quote or act on the agent's reply beyond copying its JSON block into the scratch file with the Write tool/i.test(text),
    'limits the use of the raw reply to the copy');
});

test('agent: hidden characters are removed and reported with the hidden-text flag kind', () => {
  const text = body(read(AGENT));
  assert.ok(text.includes('`hidden-text`'), 'names the hidden-text kind');
  assert.ok(scorer.FLAG_KINDS.includes('hidden-text'), 'the scorer accepts it');
});

// ─── Review round 1 (PR5-R-3, R-4, R-5, R-7, R-14) ─────────────────────────────────────────────

// PR5-R-5 (mutant m3): the contract is the table, row for row: its keys equal the scorer's closed set exactly
// (a deleted row, or an extra row such as skill_md_content, fails), not mentions anywhere in the body.
test('agent: the Output contract table rows equal AGENT_CANDIDATE_KEYS exactly', () => {
  const text = body(read(AGENT));
  const start = text.indexOf('## Output contract');
  assert.ok(start >= 0, 'has an Output contract section');
  const end = text.indexOf('\n## ', start + 1);
  const section = text.slice(start, end < 0 ? undefined : end);
  const rows = [...section.matchAll(/^\| `(\w+)` \|/gm)].map(m => m[1]);
  assert.strictEqual(new Set(rows).size, rows.length, `no duplicate rows: ${rows}`);
  assert.deepStrictEqual([...rows].sort(), [...scorer.AGENT_CANDIDATE_KEYS].sort());
});

// PR5-R-5 (mutant m6): the session never fetches; the only WebFetch/WebSearch mentions in skill-scout's body are
// the agent's tool list and the prohibition.
test('skill-scout: no WebFetch/WebSearch instruction besides the tool list and the prohibition', () => {
  const allowed = [/\(Read, WebFetch, WebSearch\)/, /Do not WebFetch registries or candidate SKILL\.md files in this session/];
  const lines = body(read(SKILL)).split('\n').filter(l => /Web(?:Fetch|Search)/.test(l));
  assert.ok(lines.length >= 1, 'the prohibition is present');
  for (const l of lines) {
    const rest = allowed.reduce((s, re) => s.replace(re, ''), l);
    assert.ok(!/Web(?:Fetch|Search)/.test(rest), `unexpected web instruction: ${l.trim().slice(0, 120)}`);
  }
});

// PR5-R-3: the agent is not a user-facing entry point; without trigger_keywords it returns no JSON.
test('agent: description routes users to the skill-scout skill; no registry count', () => {
  const desc = (frontmatter(read(AGENT)).match(/^description: \|\n([\s\S]*?)\n(?=\S)/m) || [, ''])[1];
  assert.ok(/dispatched by the skill-scout skill/i.test(desc.replace(/\s+/g, ' ')), 'says who dispatches it');
  assert.ok(/use the skill-scout skill/i.test(desc.replace(/\s+/g, ' ')), 'routes users to the skill');
  assert.ok(!/\d+\s+(?:known\s+)?registries/i.test(desc), 'no registry count');
});

test('agent: missing trigger_keywords gives no JSON and a pointer to the skill-scout skill (one closing rule)', () => {
  const text = body(read(AGENT));
  assert.ok(!/empty array/i.test(text.split('## Output contract')[0]), 'does not return [] for missing input');
  assert.ok(/no JSON/i.test(text) && /invoke the skill-scout skill/i.test(text), 'pointer instead of JSON');
  assert.strictEqual((text.match(/^## Final message/gm) || []).length, 1, 'one Final message section');
});

// PR5-R-4: Read is not used by the workflow; nothing local or from a page goes into a URL or query.
test('agent: no local reads, no page or local text in fetch URLs or search queries', () => {
  const text = body(read(AGENT)).replace(/\s+/g, ' ');
  assert.ok(/Do not read local files/i.test(text), 'no local reads');
  assert.ok(/never put local content or anything from a page into a fetch URL or search query/i.test(text), 'no exfiltration channel');
});

// PR5-R-7, R-8, R-14: step 9 is decidable from what the session sees; a reply without JSON stops; Bash is required.
test('skill-scout: step 9 without the registry clause; a reply without a JSON block stops; compatibility names Bash', () => {
  const raw = read(SKILL);
  const text = body(raw);
  assert.ok(!/registry match/i.test(text), 'no registry-match condition');
  assert.ok(/no fenced `json` block/i.test(text), 'handles a reply without a JSON block');
  assert.ok(/Agent, Write and Bash tools/.test(frontmatter(raw)), 'compatibility names Bash');
});

// ─── Review round 2 (PR5-R-16, R-19) ─────────────────────────────────────────────────────────

// PR5-R-16: the agent is given the scorer's source_url rule, the root-skill form and the drop rule.
test('agent: the source_url row states the exact rule, the root-skill form and the drop rule', () => {
  const text = body(read(AGENT));
  const row = (text.match(/^\| `source_url` \|.*$/m) || [''])[0];
  assert.ok(row.includes('[A-Za-z0-9._~+-]'), 'segment charset');
  assert.ok(/no trailing slash/i.test(row), 'no trailing slash');
  assert.ok(/no `\.` or `\.\.` segment/i.test(row), 'no dot segments');
  assert.ok(row.includes('/tree/<commit_hash>`') && /repository root/i.test(row), 'root-level skill form');
  assert.ok(/drop the candidate/i.test(row), 'drop rule');
  assert.ok(/Candidates dropped: <D>/.test(text), 'dropped candidates are counted in the closing line');
});

// PR5-R-19: step 4's no-JSON stop names both causes without guessing.
test('skill-scout: the no-JSON stop names both causes', () => {
  const text = body(read(SKILL)).replace(/\s+/g, ' ');
  assert.ok(/installed before P0-05/.test(text) && /re-run `\.\/install\.sh`/.test(text), 'stale agent cause');
  assert.ok(/without `trigger_keywords`[^.]*skill-scout bug/i.test(text), 'missing-keywords cause');
});

// ─── Review round 3 (PR5-R-20) ────────────────────────────────────────────────────────────────

// PR5-R-20: every candidate is pinned to a full 40-hex commit and its URL's ref is that commit; no date-only or
// default-branch path remains in the agent or in skill-scout.
test('agent and skill-scout: full 40-hex pin required; no date-only or default-branch rule', () => {
  const agent = body(read(AGENT));
  const row = k => (agent.match(new RegExp(`^\\| \`${k}\` \\|.*$`, 'm')) || [''])[0];
  assert.ok(/40/.test(row('commit_hash')) && /lower-?case/i.test(row('commit_hash')), 'commit_hash row states 40 lowercase hex');
  assert.ok(/drop the candidate/i.test(row('commit_hash')), 'no full sha → dropped');
  assert.ok(/optional/i.test(row('commit_date')) && /informational/i.test(row('commit_date')), 'commit_date is informational');
  assert.ok(row('source_url').includes('/tree/<commit_hash>'), 'the URL ref is the commit_hash');
  for (const [name, text] of [['agent', agent], ['skill-scout', body(read(SKILL))]]) {
    const flat = text.replace(/\s+/g, ' ');
    assert.ok(!/default branch/i.test(flat), `${name}: no default-branch rule`);
    assert.ok(!/only a (?:commit )?date|commit-date \(no hash\)|no hash was resolvable/i.test(flat), `${name}: no date-only path`);
  }
  assert.ok(/Source: github\.com\/<org>\/<repo>@<commit_hash>/.test(body(read(SKILL))), 'shortlist Source line uses the full sha');
});

// ─── Review round 4 (PR5-R-22, R-23, R-24, sha copy) ─────────────────────────────────────────

// PR5-R-22: skill-scout reads the agent's closing line only through one fixed two-integer pattern, and an empty
// array with dropped candidates is not "no suitable skill".
const CLOSING_RE_SRC = String.raw`^The calling session validates and scores this per skill-scout step 5\. Findings not tied to a returned candidate: (\d{1,2})\. Candidates dropped: (\d{1,2})\.$`;
test('skill-scout: the closing line is read only through the fixed pattern, with the three branches', () => {
  const text = body(read(SKILL));
  const flat = text.replace(/\s+/g, ' ');
  assert.ok(text.includes(CLOSING_RE_SRC), 'states the exact pattern');
  assert.ok(/empty and D > 0[^.]*could not be pinned, fetched or located[^.]*retry later/i.test(flat) && /do not go to step 9/i.test(flat), 'empty + dropped → retry, no step 9');
  assert.ok(/non-empty and D > 0[^.]*further candidates could not be pinned, fetched or located/i.test(flat), 'non-empty + dropped → one line');
  assert.ok(/does not match[^.]*counts could not be read[^.]*not conclude/i.test(flat), 'no match → counts unreadable, no conclusion');
  // Round 5, PR5-R-26: an unmatched line with a non-empty array continues and says the dropped count is unknown.
  assert.ok(/does not match[^.]*: if the array is empty[^;]*stop instead of step 9; if it is non-empty, continue[^.]*dropped count is unknown/i.test(flat),
    'unmatched line: empty → stop; non-empty → continue, dropped count unknown');
  // PR5-R-27: D covers every drop reason the agent counts.
  assert.ok(/D the number of candidates the agent dropped for any reason \(no full commit sha, SKILL\.md not fetchable at it, or a location that cannot be written as an allowed URL\)/i.test(flat),
    'D covers all drop reasons');
  assert.ok(/step 4 received an empty array with D = 0/i.test(flat), 'step 9 only for an empty array with D = 0');
});

test('agent: its closing line, filled with numbers, matches skill-scout\'s pattern exactly', () => {
  const m = body(read(AGENT)).match(/one line: "(The calling session[^"]*)"/);
  assert.ok(m, 'closing line found');
  const filled = m[1].replace(/\s+/g, ' ').replace('<N>', '3').replace('<D>', '12');
  assert.ok(new RegExp(CLOSING_RE_SRC).test(filled), `filled line: ${filled}`);
  // PR5-R-27: the agent counts every drop reason in <D>, in the same words as skill-scout.
  assert.ok(/<D> counts every candidate you dropped: no full commit sha, SKILL\.md not fetchable at it, or a location that cannot be written as an allowed URL/i
    .test(body(read(AGENT)).replace(/\s+/g, ' ')), 'agent defines <D> with all reasons');
});

// PR5-R-23, R-24: every candidate fetch is at <commit_hash> (root-skill forms included); none at main/HEAD.
test('agent: candidate fetch URLs carry <commit_hash>, with root-skill forms; none on main or HEAD', () => {
  const text = body(read(AGENT));
  const urls = [...text.matchAll(/`(https:\/\/(?:raw\.githubusercontent\.com|api\.github\.com\/repos)\/<org>[^`]*)`/g)].map(m => m[1]);
  const raw = urls.filter(u => u.startsWith('https://raw.githubusercontent.com/'));
  const contents = urls.filter(u => u.includes('/contents'));
  assert.ok(raw.length >= 2 && contents.length >= 2, `raw ${raw.length}, contents ${contents.length}`);
  for (const u of raw) assert.ok(u.includes('/<commit_hash>/'), `raw at the pin: ${u}`);
  for (const u of contents) assert.ok(u.includes('ref=<commit_hash>'), `contents at the pin: ${u}`);
  assert.ok(raw.includes('https://raw.githubusercontent.com/<org>/<repo>/<commit_hash>/SKILL.md'), 'root-skill raw form');
  assert.ok(contents.includes('https://api.github.com/repos/<org>/<repo>/contents?ref=<commit_hash>'), 'root-skill contents form');
  for (const u of urls) assert.ok(!/\/(?:main|master|HEAD)\//.test(u) && !u.includes('//SKILL.md'), `no branch or double slash: ${u}`);
});

// Round 4 (b): the sha is copied exactly as the API returns it (lowercase), since the scorer rejects upper case.
test('agent: the sha is copied exactly as the commits API returns it', () => {
  assert.ok(/exactly as the API returns it/i.test(body(read(AGENT)).replace(/\s+/g, ' ')));
});

if (!ok) process.exit(1);
console.log('\nscout-read-only-fetcher.test.js: all tests passed');
