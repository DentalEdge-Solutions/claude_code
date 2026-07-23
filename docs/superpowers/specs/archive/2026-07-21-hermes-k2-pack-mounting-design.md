# Hermes K2 — Pack Mounting + Knowledge Retrieval (design spec)

> **Date:** 2026-07-21 · **Status:** design (planning only) · **Depends on:** K0, K1
> **Master:** `specs/2026-07-20-hermes-master-architecture.md`

## Goal

Make governed domain-pack knowledge available inside a Hermes run — **credential-free**. A run
targeting (or declaring a dependency on) a domain pack should be able to read that pack's
`knowledge/` and `skills/` the same way it already reads `.claude/agents/`, and query it the same
way it queries the project brain. This is the "runs agents/teams and executes domain-pack tools"
identity from the charter, minus the "executes" part — K2 is the **read side** of pack support; the
**execute side** (a live adapter that actually calls `tools/*.tool.json` against a real API with a
real credential) is deliberately out of scope and deferred to the Operate track (H1→H3).

**K-track vs H-track:** K0/K1 are the same artifacts as H0/H0.5 (renamed here only for phase
numbering — the walking skeleton and the daemon+queue are prerequisites regardless of which track
consumes them next). K2 is the first phase of a **second, parallel track**: capability breadth for
things that need no credential (pack knowledge, retrieval, multi-pack context) versus the H1→H3
track's depth (vault, HITL, staging, budget, real credentials, VPS). K2 depends only on K0/K1 — it
does **not** depend on H1's vault and must keep working if H1 is delayed, skipped, or reordered.

### Capabilities delivered

- **(a) Retrieval** — extend the brain-search-style retrieval so `packs/*/knowledge/*.md` is
  queryable at its own declared authority, alongside (not merged into) the project brain.
- **(b) Mounting** — when a run's target declares a pack dependency, Hermes assembles the run so
  the spawned agent has that pack's `knowledge/` + `skills/` available, and can *read* (never call)
  the pack's `tools/*.tool.json` as declarative documentation.

## Non-goals (deferred to the Operate track)

Credential vault (H1), HITL pause/resume (H1), pack **tool execution** — no adapter binds a
`tools/*.tool.json` to a live API call anywhere in K2 — staging enforcement (H2), budget caps (H2),
`clients/<client>/` binding resolution (H1+, and only for the pack that owns the binding). K2 never
reads `packs/*/clients/` or `packs/*/guardrails/policy.json` for enforcement — those are inputs to
the future policy engine, not to the kernel.

## Decisions (from master §2, applied here, plus one new decision)

- **D1 Engine (reused):** the mounted knowledge reaches the agent the same way everything else
  does in the D1 model — as context the spawned `claude -p` process can read, not as new runtime
  machinery bolted onto Hermes.
- **D2 Runtime (reused):** no change; still Node ≥22, CommonJS, no new runtime dependencies.
- **D3 Persistence — runs table only:** K2 adds **no new migration and no new table**. It writes no
  durable state beyond what the `runs` row (K1) already records, plus one new per-run artifact file
  (`mount-manifest.json`, filesystem, not SQLite) alongside the existing `manifest.json`/`result.json`.
  Retrieval is computed at query time (scan + score), matching `brain-search.js`'s own no-index
  philosophy — an index is deferred until measurably slow, for packs exactly as it is for the brain.
- **D7 Daemon (reused):** mounting is a `core.execute()`-time concern; it does not touch the
  daemon/scheduler at all. A scheduled run and a direct `hermes run` mount identically.
- **D12 Credential-free kernel (new, established here):** the Hermes **kernel** — everything through
  K2 — never touches a credential, a live write, or money, regardless of what pack is mounted or
  what tier that pack declares. Pack `execution_mode` (`read-only` / `hitl` / `staging-autonomous`)
  governs what the future Operate-track **adapter** is allowed to do; it has **zero** effect on what
  K2 mounts or exposes. Every pack's tools are docs-only, unconditionally, for every pack, every
  tier — mounting the `hitl` `google-ads` pack and the `read-only` `google-analytics` pack are
  identical operations from K2's point of view. This is the boundary that makes K2 safe to build and
  ship *before* H1's vault exists, and it is the fact H1+ must never weaken for K2-mounted content.
  (Candidate for backfill into the master decision table alongside D1–D9.)

## Architecture

K2 adds three small, pure-ish modules to the existing `hermes/lib/` tree and wires them into
`core.execute()` (K1) between target resolution and `runner.run()`. Nothing here touches
`loader.js`, `runner.js`, or `result-gate.js` — H0's fail-closed tier check and injection-safe spawn
are unchanged; K2 only adds *more context*, never a new execution path.

```
hermes/
├── lib/
│   ├── loader.js          # [K0, unchanged] discoverPacks() reused, not reimplemented
│   ├── runner.js          # [K0, unchanged]
│   ├── result-gate.js     # [K0, unchanged]
│   ├── db.js               # [K1, unchanged]
│   ├── queue.js            # [K1, unchanged]
│   ├── core.js              # [K1, extended] calls pack-resolver + mount before runner.run()
│   ├── scheduler.js        # [K1, unchanged]
│   ├── pack-resolver.js    # [new] resolve a target's declared pack_deps, fail-closed
│   ├── mount.js             # [new] assemble knowledge/skills/tools into a mount manifest + briefing
│   └── knowledge.js         # [new] pack-scoped retrieval, brain-search-style
├── bin/
│   ├── hermes.js            # [K0/K1, extended] `hermes knowledge <pack> --query "..."` subcommand
│   └── hermesd.js           # [K1, unchanged]
```

**Control flow (one `hermes run <target>` with `pack_deps`):**

```
core.execute(targetId, opts):
  1. target = loader.resolveTarget(...)                      [K0, unchanged — fail-closed tier check]
  2. deps   = pack-resolver.resolvePackDeps(config, repoRoot, target)
              ├─ unresolvable pack name → HARD ERROR, nothing spawned (same fail-closed shape as K0)
              └─ ok → [{ name, execution_mode, risk_tier, ... }, ...]  (from packs/registry.json)
  3. mount  = mount.assembleMount(deps, repoRoot)             → { packs: [{knowledge[], skills[], tools[]}] }
  4. brief  = mount.renderMountBriefing(mount)                → markdown string
  5. runner.run(target, { ...opts, promptSuffix: brief })     [K0, unchanged spawn mechanics]
  6. result-gate.gate(...)                                    [K0, unchanged] writes manifest.json/result.json
  7. mount.writeMountManifest(artifactDir, mount)              → mount-manifest.json (audit trail)
```

`runner.run()` gains one new, additive option (`promptSuffix`) — appended to the existing prompt
text before argv is built. It does not change argv shape, spawn mechanics, or the injection-safe
argv-array discipline; the prompt is still one string, just a longer one.

**Why no file copying:** `packs/` already ships inside the same repo checkout the Hermes container
runs from (D8 — git pull + `docker compose build` on the VPS). Mounting is therefore *reference*
assembly — absolute paths + a rendered briefing — not a staging copy. This also satisfies the
existing repo rule "agents/packs are discovered in place; nothing is duplicated or hardcoded" (H0
spec) extended to packs' knowledge and skills.

## How mounting works

**Declaring a dependency.** `hermes.config.json` `runnable_targets` entries gain one new optional
field, `pack_deps: string[]`:

```json
{
  "id": "wp-content-review",
  "kind": "agent",
  "tier": "read-only",
  "prompt": "Review recent WordPress content changes for the client and summarize risk.",
  "pack_deps": ["wordpress"]
}
```

For a `kind: "pack"` target (H0 already resolves these against `packs/registry.json`), `pack_deps`
defaults to `[target.id]` when absent — a pack target always at least mounts itself.

**Resolving.** `pack-resolver.js` cross-checks every declared name against `discoverPacks(repoRoot)`
(K0's existing `loader.js` export, reused verbatim, not reimplemented). An undeclared or unknown
pack name is a **hard error before any subprocess exists** — the same "validation precedes
execution" guarantee K0 established for targets now extends to their pack dependencies.

**Assembling.** `mount.js` walks, per resolved pack: `packs/<name>/knowledge/*.md`,
`packs/<name>/skills/*/SKILL.md`, `packs/<name>/tools/*.tool.json`. It builds two things:

1. A **mount manifest** (JSON, written to the run's artifact dir for audit) — the exact file list,
   pack metadata (`execution_mode`, `risk_tier`, `last_reviewed`), and a `tools` array carrying only
   metadata fields (`name`, `description`, `effect`, `target`, `requires_approval`) — never the
   tool's handler, never a way to invoke it, because there is no handler in K2 to carry.
2. A **mount briefing** (markdown) prepended to the run prompt, e.g.:

   ```
   ## Mounted domain pack: wordpress (staging-autonomous, standard)
   Knowledge (read for grounding — do not assume, verify against these):
   - packs/wordpress/knowledge/staging-and-safety.md
   - packs/wordpress/knowledge/bricks-builder.md
   - packs/wordpress/knowledge/wordpress-fundamentals.md
   - packs/wordpress/knowledge/content-operations.md
   Skills (for context on how this pack is normally operated):
   - packs/wordpress/skills/wp-manage/SKILL.md
   Tools — DECLARATIVE ONLY. These describe what a future, credentialed runtime could do.
   You cannot call them; none are wired to a live API in this run. Read them to inform
   analysis or a written plan, never to imply an action was taken:
   - wp_update_content (effect: write, target: staging, requires_approval: false)
   - wp_create_post (effect: write, target: staging, requires_approval: false)
   - wp_list_content (effect: read, target: staging)
   - wp_get_content (effect: read, target: staging)
   - wp_update_bricks_template (effect: write, target: staging, requires_approval: false)
   ```

The agent reads these files with its existing (read-only) tool access — nothing new is granted.
The briefing's "declarative only" language is a **prompt-level disclosure**, not the security
control; the actual control is structural (§ Security, below): there is no tool binding, adapter,
or credential anywhere in the process for the agent to call even if it tried.

## Retrieval integration

`knowledge.js` extends the brain-search pattern (`scripts/brain/brain-search.js` /
`scripts/brain/brain-lib.js`) to `packs/*/knowledge/`, without modifying those files. It **reuses**
`brain-lib.js`'s `parseFrontmatter` and `walkMarkdown` directly (`require('../../scripts/brain/brain-lib')`)
and reimplements only the scoring's authority term, because pack knowledge is authority-tiered by
**pack governance metadata** (`pack.json`: `risk_tier`, `last_reviewed`, `review_cadence_days`), not
by the brain's directory-prefix table (`canon/`, `decisions/active/`, …) — a pack has no such
subtree structure and no `status` frontmatter field.

- `searchPack(packName, query, repoRoot, opts) → results[]` — same term-overlap + recency formula as
  `brain-search.js`'s `search()`; tier weight comes from the pack's `risk_tier` (`critical` weighs
  more than `standard`) with a staleness penalty once `last_reviewed` exceeds `review_cadence_days`
  (a pack overdue for review is still queryable, just ranked lower — visibility over silence).
  Results are tagged `authority: "pack:<name>"` so a caller can always tell brain results and pack
  results apart, even when merged.
- `searchMountedKnowledge(mountManifest, query, repoRoot, opts) → results[]` — runs `searchPack`
  across every pack in the *current run's* mount manifest and merges + re-ranks, so a mid-run agent
  (or, later, a team) can ask "what does this pack say about X" in exactly the shape it already asks
  the project brain (`brain-search.js --query`), just scoped to what was mounted.
- Deliberately **two separate query surfaces, never one merged index**: `brain-search` stays the
  project-brain tool; `knowledge.js` is the pack tool. A future federated query (brain + all mounted
  packs in one ranked list) is possible but not built here — K2 ships the primitive both directions
  need, not the federation.

CLI parity: `hermes knowledge <pack> --query "<terms>"` (new subcommand on `bin/hermes.js`) mirrors
`brain-search.js`'s CLI shape (`--query`, `--limit`, `--json`) for local dogfooding and debugging,
independent of any run.

## Data model

No new table. K2's only durable artifact is `mount-manifest.json`, filesystem JSON written to the
same `evals/hermes/runs/<run-id>/` directory K0's `result-gate` already owns — sibling to
`result.json`/`manifest.json`, not a replacement for either. The existing `runs` row (K1) is
unchanged by K2; a run that mounted packs is not distinguished at the SQL level, only in its
artifact directory. (If a future phase needs to query "which runs mounted pack X" at the DB layer,
that is a new, explicitly-scoped migration — not implied by K2.)

## Error handling

| Failure | Detection | Behavior |
|---|---|---|
| `pack_deps` names a pack absent from `packs/registry.json` | `pack-resolver` cross-check | Hard error before spawn — same fail-closed exit-2 shape as an unknown target (K0) |
| Pack directory exists in the registry but not on disk | `discoverPacks` (K0, reused) already fails this closed | Inherited from K0 — no new code path |
| Pack has an empty/missing `knowledge/` or `skills/` dir | `mount.assembleMount` globs return `[]` | Not an error — empty arrays in the manifest; briefing omits the empty section; a knowledge-free pack still mounts (e.g. a pack with tools only) |
| A `tools/*.tool.json` file is malformed JSON | `mount.assembleMount` parse | That one tool entry is skipped and recorded as a `warnings[]` entry in the mount manifest; the run is **not** failed — tool docs are informational, never load-bearing |
| `knowledge.js` query with no matches | `searchPack`/`searchMountedKnowledge` | Empty array, exit 0 — same as `brain-search.js`'s empty-result behavior |
| Mounted pack's `execution_mode` is above the *target's own* `allowed_tiers` | Not checked by K2 — deliberate | K0's tier check governs what the **target** may run; it says nothing about knowledge mounted alongside it. See D12 — mounting is unconditional and tier-independent by design, because it never grants execution |

## Security

K2's entire safety argument is structural, not policy-based — there is nothing to bypass because
there is nothing there:

1. **No adapter exists.** Grep-able fact, not a promise: no file under `hermes/lib/` for K2 imports
   or constructs an HTTP client, an OAuth flow, or anything that resolves a `tools/*.tool.json`
   `api` field into a callable function. `mount.js` only ever reads a tool file's JSON and copies a
   fixed set of metadata fields into the manifest/briefing.
2. **No credential surface.** K2 never reads `packs/*/clients/` (where a future per-client binding
   would live) and never reads `HERMES_VAULT_KEY` or anything vault-shaped (H1, not built yet
   anyway). A pack can be mounted with zero client bindings configured — mounting has no dependency
   on a client existing.
3. **Tools are text, not tools, to the spawned process.** The spawned `claude -p` process's
   permission mode is exactly what K0/K1 already grant (read-only); K2 adds prompt content, never a
   new `--allowedTools` entry, MCP server, or hook. An agent "wanting" to call `wp_update_content`
   after reading its doc has no mechanism to do so — the same way reading a recipe doesn't let you
   eat the meal.
4. **Unconditional docs-only, independent of pack tier (D12).** A `staging-autonomous` or `hitl`
   pack mounts identically to a `read-only` one. There is no branch in `mount.js` that upgrades
   exposure based on `execution_mode` — tier only ever appears in the manifest as *metadata to
   report*, never as a *condition to act on*.
5. **Auditability preserved.** Every mount is a durable `mount-manifest.json` alongside the run's
   existing manifest — "what pack knowledge/skills/tool-docs did this run see" is always answerable,
   matching K0's "what did Hermes run, with what, when" auditability posture.

The through-line from the master doc's layered security posture (§6) still holds: K2 sits entirely
inside layer 1 (tier fail-closed) and layer 7 (auditability) — it adds no new layer, because it adds
no new capability to gate.

## Testing strategy

All offline, plain `assert` (repo house style — see `scripts/brain/brain-search.test.js`,
`scripts/run-calibration.test.js`), each file run standalone via `node hermes/test/<name>.test.js`,
discovered by `run-all-tests.js` (already walks `hermes/`).

- **pack-resolver.js** — resolves a declared `pack_deps` list against a fixture `packs/registry.json`;
  fails closed on an unknown pack name; defaults `pack_deps` to `[target.id]` for `kind: "pack"`
  targets when absent; returns full registry pack objects (not just names) for downstream use.
- **mount.js** — manifest shape (`packs[].knowledge/skills/tools` arrays of correct paths) against a
  fixture pack dir tree; briefing text contains every knowledge/skill path and the "DECLARATIVE
  ONLY" tool disclaimer; a malformed `tools/*.tool.json` is skipped and recorded in `warnings[]`
  without throwing; an empty `knowledge/` dir yields `[]`, not an error.
- **knowledge.js** — term-overlap + recency scoring matches `brain-search.js`'s formula shape on a
  fixture pack knowledge dir; `risk_tier: critical` outranks `standard` at equal term overlap; a
  pack past `review_cadence_days` since `last_reviewed` ranks lower than a freshly-reviewed pack at
  equal overlap; `searchMountedKnowledge` merges + tags results from two mounted packs with distinct
  `authority: "pack:<name>"` values.
- **core.js (extended)** — integration test: a fixture target with `pack_deps` executed against a
  stub `claude` script that echoes back the prompt it received; asserts the mount briefing text is
  present in what the stub saw, and that `mount-manifest.json` exists in the run's artifact dir
  alongside `manifest.json`.
- **Boundary test (the D12 assertion, made concrete):** mount the `wordpress` pack (a write-effect,
  `staging-autonomous` pack) into a run; assert the stub `claude` process's argv/env contains no
  tool-execution surface for `wp_update_content` — no MCP server config, no `--allowedTools` entry
  naming it, no environment variable resembling a WordPress credential. The absence is the proof.

## Definition of done

- `node scripts/run-all-tests.js` → all suites green, including the five new `hermes/test/*.test.js`
  files above, alongside every K0/K1 suite (still passing, unmodified).
- `hermes run <target-with-pack_deps>` mounts the declared pack(s): the run's artifact dir contains
  `mount-manifest.json` listing every knowledge/skill/tool-doc path that was exposed.
- `hermes run <target>` with **no** `pack_deps` behaves exactly as K1 — no mount step, no
  `mount-manifest.json`, unchanged prompt. Mounting is additive, never mandatory.
- `hermes knowledge <pack> --query "<terms>"` returns ranked results from that pack's `knowledge/`,
  tagged with the pack's declared authority, mirroring `brain-search.js`'s CLI shape.
- An unresolvable `pack_deps` entry fails the run closed, before any subprocess is spawned — no
  partial mount, no silent skip.
- The boundary test above passes: a run mounting a write-effect pack has zero mechanism to execute
  that write. This is the load-bearing proof for D12.

## Out of scope (Operate track)

Tool execution adapter, credential vault, HITL approval, staging-target enforcement, budget caps,
`clients/<client>/` binding resolution, guardrails/policy.json enforcement, any change to what the
spawned `claude -p` process is permitted to do beyond reading more files. All deferred to H1 → H3,
which build **on top of** K2's mount manifest (an approved future write would still start from the
same declarative tool doc K2 already exposes) without K2 itself ever crossing the credential-free
line.
