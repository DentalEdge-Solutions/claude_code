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

  console.log('score-candidates.test.js: all assertions passed');
} finally {
  fs.rmSync(TMP, { recursive: true, force: true });
}
