// scripts/score-candidates.test.js — scoring, ranking and the CLI contract of
// skills/skill-scout/scripts/score-candidates.js (P12). Expected scores are worked out by hand
// from the weights. It lives in scripts/, not next to the script: files under skills/ ship to
// target projects, and the skill scanner blocks a child_process require there.
'use strict';
const { spawnSync } = require('child_process');
const fs = require('fs');
const os = require('os');
const path = require('path');
const assert = require('assert');

const SCRIPT = path.join(__dirname, '..', 'skills', 'skill-scout', 'scripts', 'score-candidates.js');
const TMP = fs.mkdtempSync(path.join(os.tmpdir(), 'score-candidates-test-'));

function score(candidates) {
  const file = path.join(TMP, 'candidates.json');
  fs.writeFileSync(file, JSON.stringify(candidates));
  const r = spawnSync('node', [SCRIPT, file], { encoding: 'utf8' });
  assert.strictEqual(r.status, 0, r.stderr);
  return JSON.parse(r.stdout);
}

const strong = {
  name: 'code-review',
  source_url: 'https://github.com/Anthropics/skills/tree/main/code-review',
  commit_hash: 'abc123',
  description: 'Use when reviewing code, auditing diffs; when user asks for a review',
  skill_md_lines: 45,
  has_scripts: true,
  has_reference: true,
  repo_age_days: 400,
  repo_stars: 2000,
  trigger_keywords: ['review', 'diff'],
};
const weak = {
  name: 'thing',
  source_url: 'https://github.com/someone/stuff/tree/main/thing',
  commit_hash: 'def456',
  description: 'A tool',
  skill_md_lines: 300,
  has_scripts: false,
  has_reference: false,
  repo_age_days: 3,
  repo_stars: 0,
  trigger_keywords: ['review'],
};

try {
  // 1. A strong candidate maxes every dimension: "use when" + 3 clauses + "when user" (10),
  //    reference + 45 lines (10), <=50 lines (10), both keywords hit (10), 2000 stars and
  //    400 days (10), trusted org matched case-insensitively (10), nothing installed (10).
  // 2. A weak one: 0, 6 (300 lines count for clarity even without a reference), 1 (300
  //    lines), 0, 1 (5 - 4 for a 3-day repo), 1 (unknown org, no stars, new), 10
  //    → 1.2 + 0.15 + 0.10 + 0.10 + 0.50 = 2.05 → 2 → SKIP.
  // 3. Output is sorted best first, whatever the input order.
  let out = score([weak, strong]);
  assert.deepStrictEqual(out.map(c => c.name), ['code-review', 'thing'], 'sorted best first');
  assert.deepStrictEqual(out[0].breakdown, {
    trigger_precision: 10, clarity: 10, context_footprint: 10, project_fit: 10,
    provenance: 10, source_reputation: 10, conflict_risk: 10,
  });
  assert.strictEqual(out[0].total_score, 10);
  assert.strictEqual(out[0].recommendation, 'STRONG');
  assert.strictEqual(out[0].commit_hash, 'abc123', 'identity fields pass through');
  assert.deepStrictEqual(out[1].breakdown, {
    trigger_precision: 0, clarity: 6, context_footprint: 1, project_fit: 0,
    provenance: 1, source_reputation: 1, conflict_risk: 10,
  });
  assert.strictEqual(out[1].total_score, 2);
  assert.strictEqual(out[1].recommendation, 'SKIP');

  // 4. Project fit also searches the SKILL.md body; no keywords at all is neutral (5).
  out = score([{ ...weak, skill_md_content: 'Helps with code REVIEW.' }]);
  assert.strictEqual(out[0].breakdown.project_fit, 10, 'keyword found in the SKILL.md body');
  out = score([{ ...weak, trigger_keywords: [] }]);
  assert.strictEqual(out[0].breakdown.project_fit, 5, 'no keywords → neutral');

  // 5. Conflict risk: a candidate named like an installed plugin is a full conflict (0);
  //    overlap with an installed skill description lowers it.
  out = score([{ ...strong, plugin_names: ['Code-Review'] }]);
  assert.strictEqual(out[0].breakdown.conflict_risk, 0, 'same name as an installed plugin');
  out = score([{ ...strong, installed_skill_descriptions: ['Use when reviewing code and auditing diffs'] }]);
  assert.ok(out[0].breakdown.conflict_risk < 10, 'description overlap lowers conflict risk');

  // 6. Recommendation bands: total 8+ STRONG, 6-7 GOOD, 4-5 MARGINAL, below 4 SKIP.
  //    Same strong candidate, but 120 lines (footprint 5) and no reference (clarity 6):
  //    2.5 + 1.2 + 0.75 + 1.5 + 1 + 1 + 0.5 = 8.45 → 8 → STRONG; drop the description to
  //    "Reviews code and diffs" (trigger precision 0, both keywords still hit): 5.95 → 6 → GOOD.
  out = score([{ ...strong, skill_md_lines: 120, has_reference: false }]);
  assert.strictEqual(out[0].total_score, 8);
  assert.strictEqual(out[0].recommendation, 'STRONG');
  out = score([{ ...strong, skill_md_lines: 120, has_reference: false, description: 'Reviews code and diffs' }]);
  assert.strictEqual(out[0].recommendation, 'GOOD');
  //    The weights themselves: 80 lines, no reference → 2.5 + 1.2 + 1.05 + 1.5 + 1 + 1 + 0.5
  //    = 8.75 → 9. A trigger weight of 0.20 instead of 0.25 would give 8.25 → 8.
  out = score([{ ...strong, skill_md_lines: 80, has_reference: false }]);
  assert.strictEqual(out[0].total_score, 9);

  // 6b. Both sides of every band (review P12-1): SKIP ≤ 3 | 4 ≤ MARGINAL ≤ 5 | 6 ≤ GOOD ≤ 7 |
  //     8 ≤ STRONG. Exact totals are asserted, so a moved threshold or a renamed band fails.
  //     The weak candidate contributes clarity 6 (1.2), footprint 1 (0.15), provenance 1 (0.1),
  //     reputation 1 (0.1) and conflict 10 (0.5); with no keywords, project fit is 5 (0.75).
  const edge = (cand, total, rec, label) => {
    const c = score([cand])[0];
    assert.deepStrictEqual([c.total_score, c.recommendation], [total, rec], label);
  };
  edge({ ...weak, description: '', trigger_keywords: [] }, 3, 'SKIP', 'SKIP upper edge: 2.8 → 3');
  edge({ ...weak, description: 'Use when x', trigger_keywords: [] }, 4, 'MARGINAL',
    'MARGINAL lower edge: 1.25 + 2.8 = 4.05 → 4');
  edge({ ...weak, description: 'Use when x, y; when user asks', trigger_keywords: [] }, 5, 'MARGINAL',
    'MARGINAL upper edge: 2.5 + 2.8 = 5.3 → 5');
  // GOOD lower edge (5.95 → 6) and STRONG lower edge (8.45 → 8) are asserted in 6 above.
  edge({ ...strong, skill_md_lines: 120, has_reference: false, description: 'Reviews code, diffs' }, 7, 'GOOD',
    'GOOD upper edge: 0.75 + 1.2 + 0.75 + 1.5 + 1 + 1 + 0.5 = 6.7 → 7');

  // 6c. Middle tiers (review P12-2).
  const rep = (over) => score([{ ...weak, ...over }])[0].breakdown.source_reputation;
  assert.strictEqual(rep({ repo_stars: 600 }), 7, 'reputation: 500+ stars');
  assert.strictEqual(rep({ repo_stars: 150 }), 5, 'reputation: 100+ stars');
  assert.strictEqual(rep({ repo_stars: 50, repo_age_days: 400 }), 4, 'reputation: unknown org, some stars');
  assert.strictEqual(rep({ source_url: 'https://github.com/multica-ai/x/tree/main/y' }), 10, 'tier 2 org');
  assert.strictEqual(rep({ source_url: 'https://github.com/DentalEdgeSolutions/x/tree/main/y' }), 10, 'tier 3 org');
  const prov = (over) => score([{ ...weak, ...over }])[0].breakdown.provenance;
  assert.strictEqual(prov({ repo_stars: 150, repo_age_days: 100 }), 7, 'provenance: 100+ stars, 30-179 days');
  assert.strictEqual(prov({ repo_stars: 20, repo_age_days: 20 }), 4, 'provenance: 10+ stars, under 30 days');
  const fp = (lines) => score([{ ...weak, skill_md_lines: lines }])[0].breakdown;
  assert.strictEqual(fp(180).context_footprint, 3, 'footprint: 151-200 lines');
  assert.strictEqual(fp(25).clarity, 3, 'clarity: 20-39 lines');
  assert.strictEqual(fp(10).clarity, 0, 'clarity: under 20 lines');
  // Overlap math: description words longer than 4 letters are "reviewing", "auditing", "diffs"
  // and "review" (4); the installed description shares "reviewing" (1) → (1 - 1/4) × 10 = 7.5 → 8.
  out = score([{ ...strong, installed_skill_descriptions: ['Helps when reviewing pull requests'] }]);
  assert.strictEqual(out[0].breakdown.conflict_risk, 8, 'conflict risk: one quarter overlap');
  // A plugin name counts at 70%: "review-diffs" shares 2 of 4 words → 0.5 × 0.7 = 0.35
  // → 6.5 → 7 (at full weight it would be 5).
  out = score([{ ...strong, plugin_names: ['review-diffs'] }]);
  assert.strictEqual(out[0].breakdown.conflict_risk, 7, 'plugin-name overlap weighs 70%');

  // 7. CLI contract: --help exits 0, a missing argument or unreadable JSON exits 1.
  let r = spawnSync('node', [SCRIPT, '--help'], { encoding: 'utf8' });
  assert.strictEqual(r.status, 0);
  assert.ok(r.stdout.includes('Usage'), 'help text');
  r = spawnSync('node', [SCRIPT], { encoding: 'utf8' });
  assert.strictEqual(r.status, 1, 'no argument');
  const bad = path.join(TMP, 'bad.json');
  fs.writeFileSync(bad, '{not json');
  r = spawnSync('node', [SCRIPT, bad], { encoding: 'utf8' });
  assert.strictEqual(r.status, 1, 'bad JSON');
  assert.ok(r.stderr.includes('Failed to parse input'));

  // ─── 8. Agent-output mode (P0-05, V-S5-7) ──────────────────────────────────────────────────
  // skill-scout-agent returns candidates with a closed key set and no body; skill-scout adds the
  // caller fields and runs the scorer with --agent-output. Every rejection exits 2, names the
  // candidate index and key, never echoes the offending value, and prints nothing on stdout.
  const SENTINEL = 'ZZ-SENTINEL-VALUE-ZZ';
  const runAgent = (input) => {
    const file = path.join(TMP, 'agent-input.json');
    fs.writeFileSync(file, typeof input === 'string' ? input : JSON.stringify(input));
    return spawnSync('node', [SCRIPT, '--agent-output', file], { encoding: 'utf8' });
  };
  const scoreAgent = (input) => {
    const res = runAgent(input);
    assert.strictEqual(res.status, 0, res.stderr);
    return JSON.parse(res.stdout);
  };
  const agentStrong = {
    name: 'code-review',
    source_url: 'https://github.com/Anthropics/skills/tree/main/code-review',
    commit_hash: 'abc1234',
    repo_stars: 2000,
    repo_age_days: 400,
    license: 'Apache-2.0',
    skill_md_lines: 45,
    has_scripts: true,
    has_reference: true,
    flags: [],
    description: 'Use when reviewing code, auditing diffs; when user asks for a review',
    body_keyword_hits: [],
  };
  const wrap = (cands, over = {}) => ({
    trigger_keywords: ['review', 'diff'], installed_skill_descriptions: [], plugin_names: [],
    candidates: cands, ...over,
  });
  const rejects = (input, needles, label) => {
    const res = runAgent(input);
    assert.strictEqual(res.status, 2, `${label}: expected exit 2, got ${res.status} (${res.stderr})`);
    assert.strictEqual(res.stdout, '', `${label}: nothing on stdout`);
    for (const n of [].concat(needles)) assert.ok(res.stderr.includes(n), `${label}: stderr names ${n}: ${res.stderr}`);
    assert.ok(!res.stderr.includes(SENTINEL), `${label}: the offending value is never echoed: ${res.stderr}`);
  };

  // 8a. The same strong candidate scores the same as in the legacy form (all 10s).
  out = scoreAgent(wrap([agentStrong]));
  assert.deepStrictEqual(out[0].breakdown, {
    trigger_precision: 10, clarity: 10, context_footprint: 10, project_fit: 10,
    provenance: 10, source_reputation: 10, conflict_risk: 10,
  });
  assert.strictEqual(out[0].total_score, 10);
  //     Validated fields the shortlist needs pass through; commit_date only when given.
  assert.strictEqual(out[0].commit_hash, 'abc1234');
  assert.strictEqual(out[0].license, 'Apache-2.0');
  assert.strictEqual(out[0].repo_stars, 2000);
  assert.deepStrictEqual(out[0].flags, []);
  assert.strictEqual(out[0].description, agentStrong.description);
  assert.ok(!('commit_date' in out[0]), 'no commit_date when none was given');

  // 8b. Project fit = description hits ∪ body_keyword_hits (the body is absent).
  const plain = { ...agentStrong, description: 'Use when x' };
  assert.strictEqual(scoreAgent(wrap([plain]))[0].breakdown.project_fit, 0, 'no hits anywhere');
  assert.strictEqual(scoreAgent(wrap([{ ...plain, body_keyword_hits: ['diff'] }]))[0].breakdown.project_fit, 5, 'one body hit of two');
  assert.strictEqual(scoreAgent(wrap([{ ...plain, body_keyword_hits: ['review', 'diff'] }]))[0].breakdown.project_fit, 10, 'both from the body');
  assert.strictEqual(scoreAgent(wrap([{ ...agentStrong, body_keyword_hits: ['review'] }]))[0].breakdown.project_fit, 10,
    'a keyword in both the description and the body counts once');
  assert.strictEqual(scoreAgent(wrap([{ ...plain }], { trigger_keywords: [] }))[0].breakdown.project_fit, 5, 'no keywords → neutral');
  //     The caller fields reach the scorer: an installed plugin of the same name is a full conflict.
  assert.strictEqual(scoreAgent(wrap([agentStrong], { plugin_names: ['code-review'] }))[0].breakdown.conflict_risk, 0);
  assert.strictEqual(scoreAgent(wrap([agentStrong], {
    installed_skill_descriptions: ['Helps when reviewing pull requests'] }))[0].breakdown.conflict_risk, 8);

  // 8c. A commit date instead of a hash (never a branch name).
  const dated = { ...agentStrong }; delete dated.commit_hash; dated.commit_date = '2026-10-01';
  out = scoreAgent(wrap([dated]));
  assert.strictEqual(out[0].commit_date, '2026-10-01');
  assert.ok(!('commit_hash' in out[0]) || out[0].commit_hash === undefined);
  const noCommit = { ...agentStrong }; delete noCommit.commit_hash;
  rejects(wrap([noCommit]), ['candidates[0].commit_hash'], 'neither a hash nor a date');
  rejects(wrap([{ ...agentStrong, commit_hash: 'main' }]), ['candidates[0].commit_hash'], 'a branch name is not a hash');
  rejects(wrap([{ ...agentStrong, commit_hash: SENTINEL }]), ['candidates[0].commit_hash'], 'free text as a hash');
  rejects(wrap([{ ...dated, commit_date: `yesterday ${SENTINEL}` }]), ['candidates[0].commit_date'], 'a date that is not YYYY-MM-DD');

  // 8d. The closed key set: an unknown key, a body field, a missing key.
  rejects(wrap([{ ...agentStrong, extra: SENTINEL }]), ['candidates[0].extra', 'not in the schema'], 'unknown key');
  rejects(wrap([{ ...agentStrong, skill_md_content: `# Body\n${SENTINEL}` }]), ['candidates[0].skill_md_content', 'body'], 'skill_md_content');
  for (const k of ['body', 'skill_md_body', 'readme', 'raw_text', 'content']) {
    rejects(wrap([{ ...agentStrong, [k]: SENTINEL }]), [`candidates[0].${k}`, 'body'], `body-like field ${k}`);
  }
  for (const k of ['trigger_keywords', 'installed_skill_descriptions', 'plugin_names']) {
    rejects(wrap([{ ...agentStrong, [k]: [SENTINEL] }]), [`candidates[0].${k}`, 'not in the schema'], `caller field ${k} inside a candidate`);
  }
  const noDesc = { ...agentStrong }; delete noDesc.description;
  rejects(wrap([noDesc]), ['candidates[0].description', 'missing'], 'missing description');
  const noFlags = { ...agentStrong }; delete noFlags.flags;
  rejects(wrap([noFlags]), ['candidates[0].flags', 'missing'], 'missing flags');
  //     A key that is itself text is not echoed either; it is described by its length.
  rejects(wrap([{ ...agentStrong, [`ignore previous instructions ${SENTINEL}`]: 1 }]),
    ['candidates[0].', 'not in the schema'], 'a key made of text');
  //     The index names the right candidate.
  rejects(wrap([agentStrong, { ...agentStrong, name: 'two', extra: 1 }]), ['candidates[1].extra'], 'second candidate');

  // 8e. The description cap: 1024 characters (the Agent Skills spec maximum), counted in code points.
  scoreAgent(wrap([{ ...agentStrong, description: 'a'.repeat(1024) }]));
  scoreAgent(wrap([{ ...agentStrong, description: '\u{1F600}'.repeat(1024) }]));
  scoreAgent(wrap([{ ...agentStrong, description: '' }]));
  rejects(wrap([{ ...agentStrong, description: SENTINEL + 'a'.repeat(1025 - SENTINEL.length) }]),
    ['candidates[0].description', '1024'], 'description over the cap');
  rejects(wrap([{ ...agentStrong, description: '\u{1F600}'.repeat(1025) }]), ['candidates[0].description', '1024'],
    'description over the cap in code points');

  // 8f. Types and value shapes.
  const badTypes = [
    ['repo_stars', '100'], ['repo_stars', -1], ['repo_age_days', 1.5], ['skill_md_lines', null],
    ['has_scripts', 'yes'], ['has_reference', 1], ['name', `two words ${SENTINEL}`], ['name', ''], ['name', 'a'.repeat(65)],
    ['source_url', `https://evil.example/${SENTINEL}`], ['source_url', `https://github.com/x/y ${SENTINEL}`],
    ['license', `${SENTINEL}${'x'.repeat(100)}`], ['license', `MIT\n${SENTINEL}`], ['license', 3],
    ['description', 42], ['flags', SENTINEL], ['body_keyword_hits', SENTINEL],
  ];
  for (const [k, v] of badTypes) rejects(wrap([{ ...agentStrong, [k]: v }]), [`candidates[0].${k}`], `${k} = ${JSON.stringify(v).slice(0, 30)}`);
  scoreAgent(wrap([{ ...agentStrong, license: null }]));

  // 8g. body_keyword_hits: every element one of the caller's trigger_keywords, no duplicates.
  rejects(wrap([{ ...agentStrong, body_keyword_hits: ['review', SENTINEL] }]), ['candidates[0].body_keyword_hits[1]'], 'hit outside the keywords');
  rejects(wrap([{ ...agentStrong, body_keyword_hits: ['Review'] }]), ['candidates[0].body_keyword_hits[0]'], 'hits are the caller strings verbatim');
  rejects(wrap([{ ...agentStrong, body_keyword_hits: ['diff', 'diff'] }]), ['candidates[0].body_keyword_hits[1]', 'duplicate'], 'duplicate hit');
  rejects(wrap([{ ...agentStrong, body_keyword_hits: [7] }]), ['candidates[0].body_keyword_hits[0]'], 'non-string hit');

  // 8h. flags: { location, kind, excerpt }, excerpt at most 100 characters, kind instruction | secret.
  const flag = { location: 'SKILL.md:12', kind: 'instruction', excerpt: 'x'.repeat(100) };
  out = scoreAgent(wrap([{ ...agentStrong, flags: [flag, { location: 'scripts/a.js:3', kind: 'secret', excerpt: 'looks like an API key' }] }]));
  assert.strictEqual(out[0].flags.length, 2, 'flags pass through');
  rejects(wrap([{ ...agentStrong, flags: [{ ...flag, excerpt: SENTINEL + 'x'.repeat(101 - SENTINEL.length) }] }]),
    ['candidates[0].flags[0].excerpt', '100'], 'excerpt over 100');
  rejects(wrap([{ ...agentStrong, flags: [{ ...flag, kind: SENTINEL }] }]), ['candidates[0].flags[0].kind'], 'unknown kind');
  rejects(wrap([{ ...agentStrong, flags: [{ ...flag, value: SENTINEL }] }]), ['candidates[0].flags[0].value'], 'extra flag key');
  rejects(wrap([{ ...agentStrong, flags: [{ ...flag, location: `${SENTINEL}${'l'.repeat(100)}` }] }]),
    ['candidates[0].flags[0].location'], 'location over 100');
  rejects(wrap([{ ...agentStrong, flags: [SENTINEL] }]), ['candidates[0].flags[0]'], 'a flag that is not an object');
  rejects(wrap([{ ...agentStrong, flags: Array.from({ length: 21 }, () => flag) }]), ['candidates[0].flags', '20'], 'more than 20 flags');

  // 8i. The top level: an object with exactly the caller fields and the candidates.
  rejects([agentStrong], ['object'], 'a bare array (legacy shape) in agent mode');
  rejects(wrap([agentStrong], { notes: SENTINEL }), ['notes', 'not in the schema'], 'unknown top-level key');
  rejects(wrap([agentStrong], { trigger_keywords: SENTINEL }), ['trigger_keywords'], 'keywords not an array');
  const noKw = wrap([agentStrong]); delete noKw.plugin_names;
  rejects(noKw, ['plugin_names', 'missing'], 'missing caller field');
  rejects(wrap(SENTINEL), ['candidates'], 'candidates not an array');
  rejects(wrap([SENTINEL]), ['candidates[0]'], 'a candidate that is not an object');
  //     Unparseable input: exit 1, and the parser's message (which can quote the input) is withheld.
  r = runAgent(`{"candidates": [${SENTINEL}`);
  assert.strictEqual(r.status, 1);
  assert.ok(r.stderr.includes('Failed to parse input'), r.stderr);
  assert.ok(!r.stderr.includes(SENTINEL), r.stderr);
  r = spawnSync('node', [SCRIPT, '--agent-output'], { encoding: 'utf8' });
  assert.strictEqual(r.status, 1, '--agent-output without a file');
  r = spawnSync('node', [SCRIPT, '--help'], { encoding: 'utf8' });
  assert.ok(r.stdout.includes('--agent-output'), 'help documents the agent-output mode');

  // ─── 9. Ranking tolerance (P0-05 acceptance) ───────────────────────────────────────────────
  // Committed fixtures with full bodies. The agent form is derived deterministically: the body is
  // removed and body_keyword_hits = the keywords the body contains by the scorer's own rule
  // (case-insensitive substring). Tolerance: none — the ranking, every total and every dimension
  // must be identical. (Residual, in the record: in real use the model computes the hits.)
  const FIX = JSON.parse(fs.readFileSync(path.join(__dirname, '..', 'fixtures', 'score-candidates', 'body-candidates.json'), 'utf8'));
  const caller = {
    trigger_keywords: FIX.trigger_keywords,
    installed_skill_descriptions: FIX.installed_skill_descriptions,
    plugin_names: FIX.plugin_names,
  };
  const legacyOut = score(FIX.candidates.map(c => ({ ...c, ...caller })));
  const hitsIn = body => FIX.trigger_keywords.filter(kw => body.toLowerCase().includes(kw.toLowerCase()));
  const agentForm = FIX.candidates.map(({ skill_md_content, ...rest }) => ({ ...rest, body_keyword_hits: hitsIn(skill_md_content) }));
  const agentOut = scoreAgent({ ...caller, candidates: agentForm });
  const pick = c => ({ name: c.name, total_score: c.total_score, breakdown: c.breakdown, recommendation: c.recommendation });
  assert.deepStrictEqual(agentOut.map(pick), legacyOut.map(pick), 'agent form ranks and scores exactly like the body form');
  //     The fixture discriminates: dropping the body features changes project fit and the ranking,
  //     so the equality above is not trivially true.
  const descOnly = scoreAgent({ ...caller, candidates: agentForm.map(c => ({ ...c, body_keyword_hits: [] })) });
  assert.notDeepStrictEqual(descOnly.map(pick), legacyOut.map(pick), 'body features matter on this fixture');
  assert.notDeepStrictEqual(descOnly.map(c => c.name), legacyOut.map(c => c.name), 'body features change the order');
  assert.ok(agentForm.some(c => c.body_keyword_hits.length > 0) && agentForm.length >= 5, 'fixture has body hits');

  console.log('score-candidates.test.js: all assertions passed');
} finally {
  fs.rmSync(TMP, { recursive: true, force: true });
}
