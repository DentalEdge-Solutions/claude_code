# Reference Repository Library

External repositories registered as **source material** — methodology, patterns,
candidate skills — never runtime dependencies. Source of truth:
`reference-repositories/registry.json` (schema-validated). Human table:
`reference-repositories/registry.md` (generated — never hand-edited). Per-entry
source cards: `reference-repositories/sources/<name>/source-card.md`.

## The governing rule

Every entry carries `install_policy: "do-not-install-directly"`. Skill or agent
adoption from any source goes through **scout → audit → adapt → eval**. Extracted
patterns land in `.project-brain/synthesis/` at synthesis authority — never canon,
never a direct install. Enforcement: `brain-security-guard.sh` denies direct
installs from `sources/`; `brain-reference-repo-audit.js` denies executables and
secrets inside source cards.

## Registry schema (`schemas/brain/reference-repo.schema.json`)

Each entry: `name` (kebab-case), `url`, `status` (`reference|unreachable|retired`),
`types[]` (from a fixed enum: methodology/skill-pattern/agent-pattern/candidate-skill/
eval-scenario/governance/retrieval/research/human-workflow-source), `install_policy`
(const `do-not-install-directly`), `last_reviewed` (`YYYY-MM-DD`), optional
`preferred_use[]` and `risk_notes[]`.

## Scripts

| Script | Usage |
|---|---|
| `brain-reference-repo-add.js` | `--name <n> --url <u> --types a,b [--use "…"]… [--risk "…"]… [--force]` (each `--use`/`--risk` is one item, kept verbatim; repeat the flag for more) — validates, dedupes, scaffolds a source card, regenerates registry.md |
| `brain-reference-repo-audit.js` | `--name <n>` — docs-only + no-secrets + policy + freshness; exit 3 on security violation, warnings otherwise |
| `brain-reference-repo-map.js` | `--name <n> [--json]` — parses the card's Reusable Patterns / Candidate Skills / Candidate Agents for skill-scout handoff |
| `brain-reference-repo-refresh.js` | `--name <n>` — bumps `last_reviewed` in registry + card |

## Skills

`reference-repo-add`, `reference-repo-audit`, `gstack-pattern-audit` (live GStack
analysis → `.project-brain/synthesis/gstack-patterns/`), and the generic
`reference-repo-pattern-extract` (any audited source). Each requires a clean audit
before extraction.

## The 16 seeded entries (all `reference`, `do-not-install-directly`, reviewed 2026-07-08)

| name | types |
|---|---|
| gstack | methodology, skill-pattern, agent-pattern, candidate-skill, eval-scenario |
| infinite-brain-os | governance, methodology |
| claude-memory-compiler | methodology, skill-pattern |
| second-brain-starter | methodology, human-workflow |
| karpathy-llm-wiki | methodology, governance |
| aprende-skill | skill-pattern, candidate-skill |
| gbrain | retrieval |
| gbrain-evals | eval-scenario, methodology |
| lightrag | retrieval (RAG-Anything merged upstream 2026-05) |
| graphify | retrieval, candidate-skill |
| understand-anything | retrieval, candidate-skill |
| letta-code | methodology (self-editing memory rejected for canon) |
| notebooklm-py | research, candidate-skill |
| pleaseprompto-notebooklm-skill | research, candidate-skill |
| deep-research-notebooklm | research, skill-pattern |
| kj-os-template | human-workflow (bundles a vendored .env.local — never copy plugin dirs) |

Only `gstack` ships with a full source card; the rest gain cards via
`reference-repo-add` as each is first used.

## NotebookLM research lane

NotebookLM / deep-research output enters `.project-brain/support/sources/` at
raw-source authority, then flows through compile → promote like any other content.
The three NotebookLM tools (notebooklm-py, pleaseprompto-notebooklm-skill,
deep-research-notebooklm) are registered here; adopt skills from them only through
the full pipeline. This routing is documented in each capsule's `BRAIN.md`.
