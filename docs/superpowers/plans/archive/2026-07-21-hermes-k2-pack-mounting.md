# Hermes K2 — Pack Mounting + Knowledge Retrieval Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give a Hermes run access to a domain pack's `knowledge/` and `skills/` as read context, and its `tools/*.tool.json` as declarative (never callable) documentation, plus a brain-search-style query surface over pack knowledge — all without adding a credential, a live write path, or a new database table.

**Architecture:** Three new, small modules — `lib/pack-resolver.js` (resolve + fail-closed validate a target's declared `pack_deps` against `packs/registry.json`, reusing K0's `discoverPacks`), `lib/mount.js` (assemble a mount manifest + a prompt briefing from a pack's `knowledge/`/`skills/`/`tools/`, docs-only), and `lib/knowledge.js` (pack-scoped retrieval, reusing `scripts/brain/brain-lib.js`'s `parseFrontmatter`/`walkMarkdown`, never modifying `scripts/brain/`). `lib/core.js` (K1) gains one additive call between target resolution and `runner.run()`; `bin/hermes.js` gains a `knowledge` subcommand for local querying.

**Tech Stack:** Node ≥22 (already established by K1), CommonJS, `'use strict'`. Tests are plain `require('assert')`, run as a standalone `node <file>` process — this repo's house style (`scripts/brain/brain-search.test.js`, `scripts/run-calibration.test.js`), **not** `node:test`. No new runtime dependencies.

**Spec:** `docs/superpowers/specs/2026-07-21-hermes-k2-pack-mounting-design.md` · **Master:** `docs/superpowers/specs/2026-07-20-hermes-master-architecture.md`

## Global Constraints

- Node ≥22, CommonJS, `'use strict'` — match K0/K1.
- **Tests are plain `assert`, not `node:test`.** Every test file: `'use strict'; const assert = require('assert'); ... try { <asserts>; console.log('<file>: all assertions passed'); } finally { <cleanup>; }` — run directly via `node hermes/test/<name>.test.js`. `run-all-tests.js` already discovers `hermes/` by the `*.test.js` suffix; no wiring changes needed there.
- **Credential-free, structurally.** No file added in this plan may `require('child_process')`, construct an HTTP/OAuth client, or read `packs/*/clients/` or a vault-shaped env var. Mounting only ever reads and describes; it never binds a tool name to a callable.
- **No new migration, no new table.** K2's only new durable artifact is `mount-manifest.json`, a filesystem file beside the existing `manifest.json`/`result.json` in each run's artifact dir.
- **Packs are read in place.** No file copying — `mount.js` records absolute/repo-relative paths into `packs/<name>/...`; it never stages a duplicate copy.
- **Additive only to K0/K1 files.** `core.js` and `bin/hermes.js` gain new calls/subcommands; nothing already shipped by K0/K1 changes shape or behavior when a target has no `pack_deps`.
- **Reuse, don't reimplement.** `pack-resolver.js` calls K0's `discoverPacks()`; `knowledge.js` calls `scripts/brain/brain-lib.js`'s `parseFrontmatter`/`walkMarkdown` directly — no forked copies of frontmatter parsing or markdown walking.

---

### Task 1: Pack dependency resolver (`lib/pack-resolver.js`)

**Files:**
- Create: `hermes/lib/pack-resolver.js`
- Test: `hermes/test/pack-resolver.test.js`

**Interfaces:**
- Consumes: `discoverPacks(repoRoot)` from `hermes/lib/loader.js` (K0, unchanged, reused).
- Produces:
  - `resolvePackDeps(config, repoRoot, target) → { ok: true, packs: [...] } | { ok: false, error }` —
    `target.pack_deps` (array of pack names) if present; else `[target.id]` when `target.kind ===
    'pack'`; else `[]`. Cross-checks every name against the registry; unknown name → `ok: false`
    before anything else runs. `packs` on success is the array of full registry pack objects
    (`name`, `domain`, `execution_mode`, `risk_tier`, `last_reviewed`, …), not just names.

- [ ] **Step 1: Write the failing test**

Create `hermes/test/pack-resolver.test.js`:

```js
'use strict';
const assert = require('assert');
const fs = require('fs');
const os = require('os');
const path = require('path');
const { resolvePackDeps } = require('../lib/pack-resolver');

function fixtureRepo() {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'hermes-pr-'));
  fs.mkdirSync(path.join(root, 'packs', 'wordpress'), { recursive: true });
  fs.writeFileSync(path.join(root, 'packs', 'registry.json'), JSON.stringify({
    packs: [
      { name: 'wordpress', domain: 'wordpress', version: '0.1.0', execution_mode: 'staging-autonomous', risk_tier: 'standard', last_reviewed: '2026-07-17' },
    ],
  }));
  return root;
}

const TMP_DIRS = [];
try {
  const config = {};

  // 1. Explicit pack_deps resolves to full registry objects.
  {
    const root = fixtureRepo(); TMP_DIRS.push(root);
    const target = { id: 'wp-content-review', kind: 'agent', pack_deps: ['wordpress'] };
    const r = resolvePackDeps(config, root, target);
    assert.strictEqual(r.ok, true, r.error);
    assert.strictEqual(r.packs.length, 1);
    assert.strictEqual(r.packs[0].name, 'wordpress');
    assert.strictEqual(r.packs[0].execution_mode, 'staging-autonomous');
  }

  // 2. kind:"pack" target with no explicit pack_deps defaults to [target.id].
  {
    const root = fixtureRepo(); TMP_DIRS.push(root);
    const target = { id: 'wordpress', kind: 'pack' };
    const r = resolvePackDeps(config, root, target);
    assert.strictEqual(r.ok, true, r.error);
    assert.deepStrictEqual(r.packs.map((p) => p.name), ['wordpress']);
  }

  // 3. kind:"agent" target with no pack_deps resolves to an empty, non-erroring list.
  {
    const root = fixtureRepo(); TMP_DIRS.push(root);
    const target = { id: 'repo-audit', kind: 'agent' };
    const r = resolvePackDeps(config, root, target);
    assert.strictEqual(r.ok, true, r.error);
    assert.deepStrictEqual(r.packs, []);
  }

  // 4. Fails closed on an unknown pack name — before anything else could run.
  {
    const root = fixtureRepo(); TMP_DIRS.push(root);
    const target = { id: 'ghost-review', kind: 'agent', pack_deps: ['not-a-real-pack'] };
    const r = resolvePackDeps(config, root, target);
    assert.strictEqual(r.ok, false);
    assert.match(r.error, /not-a-real-pack/);
  }

  console.log('pack-resolver.test.js: all assertions passed');
} finally {
  for (const d of TMP_DIRS) fs.rmSync(d, { recursive: true, force: true });
}
```

- [ ] **Step 2: Run to verify it fails** — `node hermes/test/pack-resolver.test.js` → `Cannot find module '../lib/pack-resolver'`.

- [ ] **Step 3: Write `lib/pack-resolver.js`**

```js
'use strict';
const { discoverPacks } = require('./loader');

function resolvePackDeps(config, repoRoot, target) {
  const declared = Array.isArray(target.pack_deps)
    ? target.pack_deps
    : (target.kind === 'pack' ? [target.id] : []);
  if (declared.length === 0) return { ok: true, packs: [] };

  const registry = discoverPacks(repoRoot);
  const packs = [];
  for (const name of declared) {
    const pack = registry.get(name);
    if (!pack) return { ok: false, error: `pack "${name}" not found in packs/registry.json` };
    packs.push(pack);
  }
  return { ok: true, packs };
}

module.exports = { resolvePackDeps };
```

- [ ] **Step 4: Run to verify it passes** — `node hermes/test/pack-resolver.test.js` → PASS (4 assertions).

- [ ] **Step 5: Commit**

```bash
git add hermes/lib/pack-resolver.js hermes/test/pack-resolver.test.js
git commit -m "feat(hermes): pack dependency resolver, fail-closed on unknown packs"
```

---

### Task 2: Mount assembler (`lib/mount.js`)

**Files:**
- Create: `hermes/lib/mount.js`
- Test: `hermes/test/mount.test.js`

**Interfaces:**
- Consumes: `packs[]` (from Task 1's `resolvePackDeps`), `repoRoot`.
- Produces:
  - `assembleMount(packs, repoRoot) → mount` — `mount.packs[]`, each `{ name, execution_mode,
    risk_tier, last_reviewed, knowledge: [relPath...], skills: [{ id, path }...], tools: [{ name,
    description, effect, target, requires_approval }...], warnings: [string...] }`. Reads
    `knowledge/*.md`, `skills/*/SKILL.md`, `tools/*.tool.json` under `packs/<name>/`. A malformed
    tool JSON file is skipped and recorded in `warnings`, never thrown.
  - `renderMountBriefing(mount) → string` — markdown, one section per pack, ending every pack's
    tool list with an explicit "DECLARATIVE ONLY" disclaimer.
  - `writeMountManifest(artifactDir, mount)` — writes `mount-manifest.json` into `artifactDir`.

- [ ] **Step 1: Write the failing test**

Create `hermes/test/mount.test.js`:

```js
'use strict';
const assert = require('assert');
const fs = require('fs');
const os = require('os');
const path = require('path');
const { assembleMount, renderMountBriefing, writeMountManifest } = require('../lib/mount');

function fixtureRepo() {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'hermes-mnt-'));
  const packDir = path.join(root, 'packs', 'wordpress');
  fs.mkdirSync(path.join(packDir, 'knowledge'), { recursive: true });
  fs.mkdirSync(path.join(packDir, 'skills', 'wp-manage'), { recursive: true });
  fs.mkdirSync(path.join(packDir, 'tools'), { recursive: true });
  fs.writeFileSync(path.join(packDir, 'knowledge', 'staging-and-safety.md'), '# Staging\n');
  fs.writeFileSync(path.join(packDir, 'skills', 'wp-manage', 'SKILL.md'), '---\nname: wp-manage\n---\n');
  fs.writeFileSync(path.join(packDir, 'tools', 'wp_update_content.tool.json'), JSON.stringify({
    name: 'wp_update_content', description: 'Update staging content', effect: 'write',
    target: 'staging', requires_approval: false,
  }));
  fs.writeFileSync(path.join(packDir, 'tools', 'broken.tool.json'), '{ not valid json');
  return root;
}

const packMeta = { name: 'wordpress', execution_mode: 'staging-autonomous', risk_tier: 'standard', last_reviewed: '2026-07-17' };

const TMP_DIRS = [];
try {
  const root = fixtureRepo(); TMP_DIRS.push(root);

  // 1. Manifest shape: knowledge, skills, tools populated; broken tool file → warning, not a throw.
  const mount = assembleMount([packMeta], root);
  assert.strictEqual(mount.packs.length, 1);
  const wp = mount.packs[0];
  assert.strictEqual(wp.name, 'wordpress');
  assert.ok(wp.knowledge.some((p) => p.endsWith('staging-and-safety.md')));
  assert.ok(wp.skills.some((s) => s.path.endsWith('wp-manage/SKILL.md')));
  assert.strictEqual(wp.tools.length, 1, 'the broken tool file must be skipped, not counted');
  assert.strictEqual(wp.tools[0].name, 'wp_update_content');
  assert.strictEqual(wp.tools[0].effect, 'write');
  assert.ok(wp.warnings.some((w) => /broken\.tool\.json/.test(w)));

  // 2. A pack with no knowledge/ dir yields [] there, not an error.
  fs.rmSync(path.join(root, 'packs', 'wordpress', 'knowledge'), { recursive: true, force: true });
  const mount2 = assembleMount([packMeta], root);
  assert.deepStrictEqual(mount2.packs[0].knowledge, []);

  // 3. Briefing text: paths present, and the declarative-only disclaimer is present.
  const briefing = renderMountBriefing(mount);
  assert.match(briefing, /wp_update_content/);
  assert.match(briefing, /DECLARATIVE ONLY/);
  assert.match(briefing, /staging-and-safety\.md/);

  // 4. writeMountManifest writes valid JSON to the given dir.
  const artifactDir = fs.mkdtempSync(path.join(os.tmpdir(), 'hermes-mnt-out-'));
  TMP_DIRS.push(artifactDir);
  writeMountManifest(artifactDir, mount);
  const written = JSON.parse(fs.readFileSync(path.join(artifactDir, 'mount-manifest.json'), 'utf8'));
  assert.strictEqual(written.packs[0].name, 'wordpress');

  console.log('mount.test.js: all assertions passed');
} finally {
  for (const d of TMP_DIRS) fs.rmSync(d, { recursive: true, force: true });
}
```

- [ ] **Step 2: Run to verify it fails** — `node hermes/test/mount.test.js` → `Cannot find module '../lib/mount'`.

- [ ] **Step 3: Write `lib/mount.js`**

```js
'use strict';
const fs = require('fs');
const path = require('path');

function listMarkdown(dir) {
  if (!fs.existsSync(dir)) return [];
  return fs.readdirSync(dir).filter((f) => f.endsWith('.md')).sort()
    .map((f) => path.join(dir, f));
}

function listSkills(dir) {
  if (!fs.existsSync(dir)) return [];
  const out = [];
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    if (!entry.isDirectory()) continue;
    const skillPath = path.join(dir, entry.name, 'SKILL.md');
    if (fs.existsSync(skillPath)) out.push({ id: entry.name, path: skillPath });
  }
  return out;
}

function listTools(dir, warnings) {
  if (!fs.existsSync(dir)) return [];
  const out = [];
  for (const f of fs.readdirSync(dir).filter((f) => f.endsWith('.tool.json')).sort()) {
    const p = path.join(dir, f);
    try {
      const doc = JSON.parse(fs.readFileSync(p, 'utf8'));
      out.push({
        name: doc.name, description: doc.description, effect: doc.effect,
        target: doc.target, requires_approval: !!doc.requires_approval,
      });
    } catch (e) {
      warnings.push(`skipped unparseable tool doc ${path.relative(dir, p)}: ${e.message}`);
    }
  }
  return out;
}

function assembleMount(packs, repoRoot) {
  const out = { packs: [] };
  for (const pack of packs) {
    const base = path.join(repoRoot, 'packs', pack.name);
    const warnings = [];
    out.packs.push({
      name: pack.name,
      execution_mode: pack.execution_mode,
      risk_tier: pack.risk_tier,
      last_reviewed: pack.last_reviewed,
      knowledge: listMarkdown(path.join(base, 'knowledge')),
      skills: listSkills(path.join(base, 'skills')),
      tools: listTools(path.join(base, 'tools'), warnings),
      warnings,
    });
  }
  return out;
}

function renderMountBriefing(mount) {
  const sections = mount.packs.map((p) => {
    const lines = [`## Mounted domain pack: ${p.name} (${p.execution_mode}, ${p.risk_tier})`];
    if (p.knowledge.length) {
      lines.push('Knowledge (read for grounding — verify against these, do not assume):');
      lines.push(...p.knowledge.map((k) => `- ${k}`));
    }
    if (p.skills.length) {
      lines.push('Skills (context on how this pack is normally operated):');
      lines.push(...p.skills.map((s) => `- ${s.path}`));
    }
    if (p.tools.length) {
      lines.push(
        'Tools — DECLARATIVE ONLY. These describe what a future, credentialed runtime',
        'could do. You cannot call them; none are wired to a live API in this run.',
        'Read them to inform analysis or a written plan, never to imply an action was taken:'
      );
      lines.push(...p.tools.map((t) => `- ${t.name} (effect: ${t.effect}, target: ${t.target}, requires_approval: ${t.requires_approval})`));
    }
    return lines.join('\n');
  });
  return sections.join('\n\n');
}

function writeMountManifest(artifactDir, mount) {
  fs.mkdirSync(artifactDir, { recursive: true });
  fs.writeFileSync(path.join(artifactDir, 'mount-manifest.json'), JSON.stringify(mount, null, 2));
}

module.exports = { assembleMount, renderMountBriefing, writeMountManifest };
```

- [ ] **Step 4: Run to verify it passes** — `node hermes/test/mount.test.js` → PASS (all assertions).

- [ ] **Step 5: Commit**

```bash
git add hermes/lib/mount.js hermes/test/mount.test.js
git commit -m "feat(hermes): mount assembler — knowledge/skills context + docs-only tool briefing"
```

---

### Task 3: Pack knowledge retrieval (`lib/knowledge.js`)

**Files:**
- Create: `hermes/lib/knowledge.js`
- Test: `hermes/test/knowledge.test.js`

**Interfaces:**
- Consumes: `parseFrontmatter`, `walkMarkdown` from `scripts/brain/brain-lib.js` (required directly,
  not reimplemented); a pack's `pack.json` (`risk_tier`, `last_reviewed`, `review_cadence_days`).
- Produces:
  - `searchPack(packName, query, repoRoot, opts={ limit }) → results[]` — same term-overlap +
    recency scoring shape as `brain-search.js`'s `search()`, with tier weight sourced from the
    pack's own `risk_tier`/staleness rather than a directory-prefix table. Each result tagged
    `authority: "pack:<name>"`.
  - `searchMountedKnowledge(mountManifest, query, repoRoot, opts) → results[]` — runs `searchPack`
    across every pack named in `mountManifest.packs[]` and merges + re-ranks.

- [ ] **Step 1: Write the failing test**

Create `hermes/test/knowledge.test.js`:

```js
'use strict';
const assert = require('assert');
const fs = require('fs');
const os = require('os');
const path = require('path');
const { searchPack, searchMountedKnowledge } = require('../lib/knowledge');

function writePack(root, name, { riskTier = 'standard', lastReviewed = '2026-07-17', docs = {} }) {
  const base = path.join(root, 'packs', name);
  fs.mkdirSync(path.join(base, 'knowledge'), { recursive: true });
  fs.writeFileSync(path.join(base, 'pack.json'), JSON.stringify({
    name, risk_tier: riskTier, last_reviewed: lastReviewed, review_cadence_days: 180,
  }));
  for (const [fname, body] of Object.entries(docs)) {
    fs.writeFileSync(path.join(base, 'knowledge', fname), body);
  }
}

const TMP_DIRS = [];
try {
  // 1. Basic term match returns the doc; no match returns [].
  {
    const root = fs.mkdtempSync(path.join(os.tmpdir(), 'hermes-kn-'));
    TMP_DIRS.push(root);
    writePack(root, 'wordpress', { docs: { 'staging.md': 'Always target staging, never production.\n' } });
    const hits = searchPack('wordpress', 'staging production', root);
    assert.strictEqual(hits.length, 1);
    assert.strictEqual(hits[0].authority, 'pack:wordpress');
    assert.deepStrictEqual(searchPack('wordpress', 'zzzznomatch', root), []);
  }

  // 2. At equal term overlap, risk_tier: critical outranks standard.
  {
    const root = fs.mkdtempSync(path.join(os.tmpdir(), 'hermes-kn-'));
    TMP_DIRS.push(root);
    writePack(root, 'google-ads', { riskTier: 'critical', docs: { 'budgets.md': 'Set a daily budget cap.\n' } });
    writePack(root, 'google-analytics', { riskTier: 'standard', docs: { 'budgets.md': 'Set a daily budget cap.\n' } });
    const adsHit = searchPack('google-ads', 'daily budget cap', root)[0];
    const gaHit = searchPack('google-analytics', 'daily budget cap', root)[0];
    assert.ok(adsHit.score > gaHit.score, `critical (${adsHit.score}) must outrank standard (${gaHit.score}) at equal overlap`);
  }

  // 3. A pack overdue for review (last_reviewed far past review_cadence_days) ranks lower
  //    than a freshly-reviewed pack at equal overlap, but is still returned (not hidden).
  {
    const root = fs.mkdtempSync(path.join(os.tmpdir(), 'hermes-kn-'));
    TMP_DIRS.push(root);
    writePack(root, 'fresh-pack', { lastReviewed: new Date().toISOString().slice(0, 10), docs: { 'k.md': 'quarterly review checklist\n' } });
    writePack(root, 'stale-pack', { lastReviewed: '2020-01-01', docs: { 'k.md': 'quarterly review checklist\n' } });
    const freshHit = searchPack('fresh-pack', 'quarterly review checklist', root)[0];
    const staleHit = searchPack('stale-pack', 'quarterly review checklist', root)[0];
    assert.ok(freshHit.score > staleHit.score);
    assert.ok(staleHit); // still returned, not filtered out
  }

  // 4. searchMountedKnowledge merges results from multiple mounted packs, each tagged distinctly.
  {
    const root = fs.mkdtempSync(path.join(os.tmpdir(), 'hermes-kn-'));
    TMP_DIRS.push(root);
    writePack(root, 'wordpress', { docs: { 'a.md': 'shared keyword content one\n' } });
    writePack(root, 'google-ads', { docs: { 'b.md': 'shared keyword content two\n' } });
    const mountManifest = { packs: [{ name: 'wordpress' }, { name: 'google-ads' }] };
    const merged = searchMountedKnowledge(mountManifest, 'shared keyword content', root);
    const authorities = new Set(merged.map((r) => r.authority));
    assert.deepStrictEqual(authorities, new Set(['pack:wordpress', 'pack:google-ads']));
  }

  console.log('knowledge.test.js: all assertions passed');
} finally {
  for (const d of TMP_DIRS) fs.rmSync(d, { recursive: true, force: true });
}
```

- [ ] **Step 2: Run to verify it fails** — `node hermes/test/knowledge.test.js` → `Cannot find module '../lib/knowledge'`.

- [ ] **Step 3: Write `lib/knowledge.js`**

```js
'use strict';
const fs = require('fs');
const path = require('path');
const { parseFrontmatter, walkMarkdown } = require('../../scripts/brain/brain-lib');

const RISK_TIER_WEIGHT = { critical: 50, standard: 30 };

// Deliberately not exported from brain-lib.js (a one-line pure helper, not worth
// sharing surface area for) — kept identical in shape to brain-search.js's own tokenizer.
function tokenize(s) {
  return String(s).toLowerCase().split(/[^a-z0-9]+/).filter((t) => t.length > 2);
}

function loadPackMeta(repoRoot, packName) {
  const p = path.join(repoRoot, 'packs', packName, 'pack.json');
  return fs.existsSync(p) ? JSON.parse(fs.readFileSync(p, 'utf8')) : {};
}

function searchPack(packName, query, repoRoot, opts = {}) {
  const limit = opts.limit || 5;
  const terms = [...new Set(tokenize(query))];
  if (!terms.length) return [];

  const meta = loadPackMeta(repoRoot, packName);
  const tierWeight = RISK_TIER_WEIGHT[meta.risk_tier] || 20;
  const reviewedAgo = meta.last_reviewed ? (Date.now() - Date.parse(meta.last_reviewed)) / 86400000 : Infinity;
  const overdueDays = Math.max(0, reviewedAgo - (meta.review_cadence_days || 180));
  const stalenessPenalty = Math.min(15, overdueDays / 30); // caps so a stale pack is de-ranked, never buried

  const knowledgeDir = path.join(repoRoot, 'packs', packName, 'knowledge');
  const results = [];
  for (const file of walkMarkdown(knowledgeDir)) {
    const rel = path.relative(repoRoot, file).split(path.sep).join('/');
    const text = fs.readFileSync(file, 'utf8');
    const { fields } = parseFrontmatter(text);
    const title = (fields && fields.title) || path.basename(rel, '.md');
    const bodyTokens = new Set(tokenize(text));
    const titleTokens = new Set(tokenize(title));
    let overlap = 0;
    for (const t of terms) {
      if (titleTokens.has(t)) overlap += 3;
      if (bodyTokens.has(t)) overlap += 1;
    }
    if (overlap === 0) continue;
    const score = Math.round((tierWeight - stalenessPenalty + overlap * 2) * 10) / 10;
    results.push({ path: rel, title, score, authority: `pack:${packName}`, pack: packName });
  }
  results.sort((a, b) => b.score - a.score || a.path.localeCompare(b.path));
  return results.slice(0, limit);
}

function searchMountedKnowledge(mountManifest, query, repoRoot, opts = {}) {
  const merged = (mountManifest.packs || [])
    .flatMap((p) => searchPack(p.name, query, repoRoot, opts));
  merged.sort((a, b) => b.score - a.score || a.path.localeCompare(b.path));
  return opts.limit ? merged.slice(0, opts.limit) : merged;
}

module.exports = { searchPack, searchMountedKnowledge };
```

- [ ] **Step 4: Run to verify it passes** — `node hermes/test/knowledge.test.js` → PASS (all assertions).

- [ ] **Step 5: Commit**

```bash
git add hermes/lib/knowledge.js hermes/test/knowledge.test.js
git commit -m "feat(hermes): pack-scoped knowledge retrieval, brain-search-style scoring"
```

---

### Task 4: Wire mounting into `core.execute()` + `hermes knowledge` subcommand

**Files:**
- Modify: `hermes/lib/core.js` (K1) — call `pack-resolver` + `mount` between target resolution and `runner.run()`
- Modify: `hermes/lib/runner.js` (K0) — accept an additive `opts.promptSuffix`
- Modify: `hermes/bin/hermes.js` — add the `knowledge <pack> --query "..."` subcommand
- Test: `hermes/test/core-mount.test.js`

**Interfaces:**
- `core.execute(targetArg, opts)` gains no new required option; when the resolved target has
  `pack_deps` (or is `kind: "pack"`), it now also returns `{ ...existing, mount }` and writes
  `mount-manifest.json` beside `manifest.json` in the run's artifact dir.
- `runner.run(target, opts)` — `opts.promptSuffix` (string, optional) is appended to the built
  prompt text before argv construction; omitted entirely when absent, so K0/K1 behavior for
  pack-free targets is byte-for-byte unchanged.

- [ ] **Step 1: Write the failing test**

Create `hermes/test/core-mount.test.js`:

```js
'use strict';
const assert = require('assert');
const fs = require('fs');
const os = require('os');
const path = require('path');
const { openDb } = require('../lib/db');
const { execute } = require('../lib/core');

function fixtureRepo() {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'hermes-cm-'));
  fs.mkdirSync(path.join(root, '.claude', 'agents'), { recursive: true });
  fs.mkdirSync(path.join(root, 'hermes'), { recursive: true });
  fs.mkdirSync(path.join(root, 'packs', 'wordpress', 'knowledge'), { recursive: true });
  fs.writeFileSync(path.join(root, 'packs', 'wordpress', 'knowledge', 'staging.md'), '# Staging discipline\n');
  fs.writeFileSync(path.join(root, 'packs', 'registry.json'), JSON.stringify({
    packs: [{ name: 'wordpress', domain: 'wordpress', version: '0.1.0', execution_mode: 'staging-autonomous', risk_tier: 'standard', last_reviewed: '2026-07-17' }],
  }));
  fs.writeFileSync(path.join(root, '.claude', 'agents', 'wp-content-review.md'), '# demo');
  fs.writeFileSync(path.join(root, 'hermes', 'hermes.config.json'), JSON.stringify({
    allowed_tiers: ['read-only'], runs_dir: 'evals/hermes/runs',
    runnable_targets: [{
      id: 'wp-content-review', kind: 'agent', tier: 'read-only', prompt: 'Review recent content.',
      pack_deps: ['wordpress'],
    }],
  }));
  return root;
}

// Stub `claude` that writes whatever prompt it received to a sentinel file, so the
// test can assert on exactly what the spawned process saw — without a real API call.
function stubThatEchoesArgv(sentinelPath) {
  const p = path.join(fs.mkdtempSync(path.join(os.tmpdir(), 'hermes-cm-bin-')), 'claude');
  fs.writeFileSync(p, `#!/usr/bin/env node
const fs = require('fs');
fs.writeFileSync(${JSON.stringify(sentinelPath)}, JSON.stringify(process.argv.slice(2)));
process.stdout.write(JSON.stringify({ ok: true }));
`, { mode: 0o755 });
  return p;
}

const TMP_DIRS = [];
try {
  const root = fixtureRepo(); TMP_DIRS.push(root);
  const d = openDb(path.join(root, 'hermes', 'state', 'hermes.db'));
  const sentinel = path.join(root, 'sentinel.json');
  const bin = stubThatEchoesArgv(sentinel);

  const out = execute('wp-content-review', { repoRoot: root, claudeBin: bin, db: d });

  // 1. The run still succeeds and writes the K0/K1 artifacts unchanged.
  assert.strictEqual(out.status, 'pass');
  assert.ok(fs.existsSync(path.join(out.artifactDir, 'manifest.json')));

  // 2. mount-manifest.json is written beside it, naming the mounted pack + its knowledge doc.
  const mountManifest = JSON.parse(fs.readFileSync(path.join(out.artifactDir, 'mount-manifest.json'), 'utf8'));
  assert.strictEqual(mountManifest.packs[0].name, 'wordpress');
  assert.ok(mountManifest.packs[0].knowledge.some((k) => k.endsWith('staging.md')));

  // 3. The spawned process actually received the mount briefing in its prompt argv.
  const argvSeen = JSON.parse(fs.readFileSync(sentinel, 'utf8'));
  const promptArg = argvSeen[argvSeen.length - 1];
  assert.match(promptArg, /Mounted domain pack: wordpress/);
  assert.match(promptArg, /DECLARATIVE ONLY/);

  console.log('core-mount.test.js: all assertions passed');
} finally {
  for (const d of TMP_DIRS) fs.rmSync(d, { recursive: true, force: true });
}
```

- [ ] **Step 2: Run to verify it fails** — `node hermes/test/core-mount.test.js` → fails (no mount step wired yet; `mount-manifest.json` never written).

- [ ] **Step 3: Extend `lib/runner.js` with `opts.promptSuffix`**

In `runner.run(target, opts)`, where the prompt string is built for argv, change:

```js
const prompt = opts.promptSuffix ? `${target.prompt}\n\n${opts.promptSuffix}` : target.prompt;
```

and use `prompt` (not `target.prompt`) in the argv array. This is the only change to `runner.js` —
argv shape, the argv-array injection-safe discipline, and every existing K0 test are unaffected
when `opts.promptSuffix` is undefined.

- [ ] **Step 4: Extend `lib/core.js`'s `execute()`**

```js
'use strict';
const path = require('path');
const { loadConfig, resolveTarget } = require('./loader');
const runner = require('./runner');
const { gate, getGitSha } = require('./result-gate');
const { finish } = require('./queue');
const { resolvePackDeps } = require('./pack-resolver');
const { assembleMount, renderMountBriefing, writeMountManifest } = require('./mount');

// ... upsertRunning() unchanged from K1 ...

function execute(targetArg, opts = {}) {
  const repoRoot = opts.repoRoot || path.resolve(__dirname, '..', '..');
  const config = opts.config || loadConfig(repoRoot);
  const now = opts.now || new Date();

  const target = typeof targetArg === 'string'
    ? (() => {
        const r = resolveTarget(config, repoRoot, targetArg);
        if (!r.ok) throw Object.assign(new Error(r.error), { code: 'VALIDATION' });
        return r.target;
      })()
    : targetArg;

  const depsResult = resolvePackDeps(config, repoRoot, target);
  if (!depsResult.ok) throw Object.assign(new Error(depsResult.error), { code: 'VALIDATION' });
  const mount = depsResult.packs.length ? assembleMount(depsResult.packs, repoRoot) : null;
  const promptSuffix = mount ? renderMountBriefing(mount) : undefined;

  const runResult = runner.run(target, { cwd: repoRoot, claudeBin: opts.claudeBin, now, promptSuffix });
  const gitSha = getGitSha(repoRoot);

  if (opts.db) upsertRunning(opts.db, runResult.runId, target, now);
  const result = gate(target, runResult, config, { repoRoot, gitSha });
  if (mount) writeMountManifest(result.artifactDir, mount);

  const status =
    runResult.error?.type === 'ENOENT' ? 'failed'
    : runResult.error?.type === 'TIMEOUT' ? 'failed'
    : result.status === 'pass' ? 'done'
    : 'failed';

  if (opts.db) finish(opts.db, runResult.runId, { status, exitCode: runResult.code, gitSha }, now);

  return { status: result.status, exitCode: runResult.code, runId: runResult.runId, artifactDir: result.artifactDir, engineError: runResult.error, mount };
}

module.exports = { execute };
```

Note: `resolvePackDeps` failing closed happens *before* `runner.run()` is called — mounting inherits
the same "validation precedes execution" ordering K0 established for the target itself.

- [ ] **Step 5: Add the `knowledge` subcommand to `bin/hermes.js`**

Extend `main` to handle `['knowledge', <pack>, '--query', <terms>]`: call
`knowledge.searchPack(pack, terms, repoRoot, { limit })`, print `score  path — title` lines (mirror
`brain-search.js`'s human-format output), `--json` prints the raw array, exit 0. No pack resolution
against a target is needed here — this is a standalone query tool, not a run.

- [ ] **Step 6: Run to verify it passes** — `node hermes/test/core-mount.test.js` → PASS; re-run every
  prior K0/K1/K2 suite to confirm nothing regressed: `node scripts/run-all-tests.js` → all green.

- [ ] **Step 7: Commit**

```bash
git add hermes/lib/core.js hermes/lib/runner.js hermes/bin/hermes.js hermes/test/core-mount.test.js
git commit -m "feat(hermes): wire pack mounting into core.execute(); add hermes knowledge subcommand"
```

---

### Task 5: Boundary test — a mounted write-effect pack has no execution path (the D12 proof)

**Files:**
- Test: `hermes/test/mount-boundary.test.js`

**Interfaces:** none new — this task adds only a test, deliberately kept separate from Task 4's
functional test so it reads as a standalone, auditable proof of the spec's D12 decision.

- [ ] **Step 1: Write the test**

Create `hermes/test/mount-boundary.test.js`:

```js
'use strict';
const assert = require('assert');
const fs = require('fs');
const os = require('os');
const path = require('path');
const { openDb } = require('../lib/db');
const { execute } = require('../lib/core');

function fixtureRepo() {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'hermes-bd-'));
  fs.mkdirSync(path.join(root, '.claude', 'agents'), { recursive: true });
  fs.mkdirSync(path.join(root, 'hermes'), { recursive: true });
  fs.mkdirSync(path.join(root, 'packs', 'wordpress', 'tools'), { recursive: true });
  fs.writeFileSync(path.join(root, 'packs', 'wordpress', 'tools', 'wp_update_content.tool.json'), JSON.stringify({
    name: 'wp_update_content', description: 'Update staging content', effect: 'write',
    target: 'staging', requires_approval: false, api: 'WordPress REST API (POST /wp/v2/{type}/{id})',
  }));
  fs.writeFileSync(path.join(root, 'packs', 'registry.json'), JSON.stringify({
    packs: [{ name: 'wordpress', domain: 'wordpress', version: '0.1.0', execution_mode: 'staging-autonomous', risk_tier: 'standard', last_reviewed: '2026-07-17' }],
  }));
  fs.writeFileSync(path.join(root, '.claude', 'agents', 'wp-content-review.md'), '# demo');
  fs.writeFileSync(path.join(root, 'hermes', 'hermes.config.json'), JSON.stringify({
    allowed_tiers: ['read-only'], runs_dir: 'evals/hermes/runs',
    runnable_targets: [{
      id: 'wp-content-review', kind: 'agent', tier: 'read-only', prompt: 'Review recent content.',
      pack_deps: ['wordpress'],
    }],
  }));
  return root;
}

// The stub records every env var name it sees and its own full argv — the two places
// a real tool-execution wiring would necessarily show up (an --allowedTools/MCP config
// argument, or a credential in the environment).
function stubThatRecordsSurface(sentinelPath) {
  const p = path.join(fs.mkdtempSync(path.join(os.tmpdir(), 'hermes-bd-bin-')), 'claude');
  fs.writeFileSync(p, `#!/usr/bin/env node
const fs = require('fs');
fs.writeFileSync(${JSON.stringify(sentinelPath)}, JSON.stringify({
  argv: process.argv.slice(2),
  envKeys: Object.keys(process.env),
}));
process.stdout.write(JSON.stringify({ ok: true }));
`, { mode: 0o755 });
  return p;
}

const TMP_DIRS = [];
try {
  const root = fixtureRepo(); TMP_DIRS.push(root);
  const d = openDb(path.join(root, 'hermes', 'state', 'hermes.db'));
  const sentinel = path.join(root, 'sentinel.json');
  const bin = stubThatRecordsSurface(sentinel);

  const out = execute('wp-content-review', { repoRoot: root, claudeBin: bin, db: d });
  assert.strictEqual(out.status, 'pass');

  const surface = JSON.parse(fs.readFileSync(sentinel, 'utf8'));

  // 1. No argv entry names the tool as something to call (no --allowedTools/MCP-shaped flag
  //    naming it) — the only place it may legally appear is inside the prompt text as a doc.
  const nonPromptArgv = surface.argv.slice(0, -1); // last element is the prompt string
  assert.ok(!nonPromptArgv.some((a) => /wp_update_content/.test(a)),
    'wp_update_content must never appear outside the prompt text — proves no tool-binding flag was added');

  // 2. No environment variable resembling a WordPress credential reached the process.
  assert.ok(!surface.envKeys.some((k) => /WORDPRESS|WP_|SITE_TOKEN|API_KEY/i.test(k)),
    `no credential-shaped env var may reach the spawned process; saw: ${surface.envKeys.join(', ')}`);

  // 3. The prompt DID receive the tool as a doc (mounting worked) — the absence above is
  //    a deliberate omission of execution machinery, not a failure to mount at all.
  assert.match(surface.argv[surface.argv.length - 1], /wp_update_content/);

  console.log('mount-boundary.test.js: all assertions passed');
} finally {
  for (const d of TMP_DIRS) fs.rmSync(d, { recursive: true, force: true });
}
```

- [ ] **Step 2: Run to verify it passes** — `node hermes/test/mount-boundary.test.js` → PASS. If it
  fails, the failure means the Task 4 wiring leaked something past prompt text — treat that as a
  design violation of D12, not a test to loosen.

- [ ] **Step 3: Final full-suite run** — `node scripts/run-all-tests.js` → every K0, K1, and K2 suite
  green.

- [ ] **Step 4: Commit**

```bash
git add hermes/test/mount-boundary.test.js
git commit -m "test(hermes): boundary proof — mounted write-effect pack has no execution surface (D12)"
```

---

## Definition of done (K2)

- [ ] `node scripts/run-all-tests.js` → all suites green: `pack-resolver`, `mount`, `knowledge`,
      `core-mount`, `mount-boundary`, alongside every unmodified K0/K1 suite.
- [ ] `hermes run <target-with-pack_deps>` writes `mount-manifest.json` in the run's artifact dir,
      listing every mounted knowledge/skill/tool-doc path.
- [ ] `hermes run <target>` with no `pack_deps` is byte-for-byte unchanged from K1 — no mount step,
      no `mount-manifest.json`, no prompt suffix.
- [ ] `hermes knowledge <pack> --query "<terms>"` returns ranked, pack-tagged results.
- [ ] An unresolvable `pack_deps` entry fails the run closed, before any subprocess spawns.
- [ ] The boundary test (Task 5) passes: mounting a write-effect (`staging-autonomous`) pack leaves
      zero execution surface for the spawned process — no tool-binding argv, no credential env var.

## Out of scope

Tool execution adapter, credential vault, HITL approval, staging-target enforcement, budget caps,
`clients/<client>/` binding resolution, `guardrails/policy.json` enforcement — all deferred to the
Operate track (H1 → H3; see `specs/2026-07-20-hermes-h1-vault-hitl-design.md` and later). K2 ships
the declarative surface those phases will eventually bind to; it never binds anything itself.
