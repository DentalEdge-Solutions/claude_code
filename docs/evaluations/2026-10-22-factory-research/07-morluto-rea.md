# Morluto — REA (Reverse Engineer Anything): technical deep dive

> Repository: https://github.com/morluto/rea (whole repository; npm package `rea-agents`) · Evaluated commit: 7091be291c2c195ea9fcc368464374a9b7d82b62 (2026-10-23 03:21:05 +0800 = 2026-10-22 19:21 UTC) on `main`
> Other branches inspected: none cloned (181 remote branch names listed via `git ls-remote` only) · License: MIT (`LICENSE`, "Copyright (c) 2026 morluto"); third-party material under `licenses/`, `THIRD_PARTY_NOTICES.md`
> Accessed: 2026-10-22 · Method: read-only shallow clone; no code executed (no install, build, test or CLI run). `gh api` used for read-only metadata.
> Legend: [F] verified fact · [I] inference · [C] unverified claim · [U] unknown

## 1. Summary

REA is a local MCP server and a CLI (`rea`, package `rea-agents`) that give a coding agent reverse-engineering
tools over shipped artifacts: native binaries (through Hopper, Ghidra, IDA, Kuna, Rizin, objdump), JavaScript/Electron
bundles and ASARs, .NET assemblies, Android APKs, firmware, browser and Electron runtimes, network/packet captures,
SQLite files, WASM, EVM bytecode and about twenty other formats (`README.md:183-217`) [F]. The pitch is "See a
feature you like. Understand how it works, down to the binary level" (`README.md:10`) and "build a version for your
project" (`README.md:61`) [C]. It is written in TypeScript (Node ≥ 22.19) with Java/Python/Swift bridges that run inside the
external analysis engines (`docs/architecture.mermaid`) [F].

It is **not a software factory in the orchestration sense**. REA deliberately contains no planner, no agent loop
and no multi-agent coordinator: the host agent (Claude Code, Codex, Cursor and others) drives the investigation,
and REA supplies deterministic, typed, evidence-producing tools plus one large workflow skill and six MCP prompts
(`docs/mcp-prompts.md:1-18`; `docs/roadmap.md:20-25` "custom orchestration needs a demonstrated requirement") [F].
What it does contribute to a factory is the **reverse-engineering and parity-verification layer**: a
content-addressed Evidence model with an authority vocabulary, residual-unknown tracking, version/source-to-bundle
comparison, and a fail-closed **reconstruction obligation ledger** that decides whether a reimplementation has
proved each required behaviour at a comparable authority (`docs/reconstruction-obligation-ledgers.md`) [F].

Category: **reverse-engineering/replication** (primary) · **other — MCP tool server / analysis platform** ·
a small **skill pack** (one product skill, four maintainer skills under `.agents/skills/`). Execution model
inside REA is deterministic code; the investigation itself is LLM-driven by the host.

Maturity: very active and very large. Created 2026-04-14; about 4,296 commits; 38 releases, latest
`rea-agents-6.7.0` published 2026-10-18 with six major versions in three months (`CHANGELOG.md`, `gh api`
releases) [F]. 5,481 tracked files, about 1,900 non-test TypeScript source files and 2,081 `*.test.*` files [F].
GitHub reports 365,013 stars, 91,511 forks, 948 open issues and 635 open PRs (gh api, 2026-10-22) [F as metadata;
whether this popularity is organic is U]. Main was in the middle of a bulk merge on the evaluation day: of the
last 100 completed `ci.yml` runs on main created on or before 2026-10-22 20:00Z, 19 succeeded, 14 failed, 66 were
cancelled and 1 was `action_required` (`gh api actions/workflows/ci.yml/runs?branch=main&status=completed`); the
evaluated commit is "test: repair remaining bulk-merge regression fixtures (#6375)" and its `CI` run, pending at
first access, has since concluded `cancelled` [F].

## 2. Architecture

Layering is documented in `docs/architecture.mermaid` and in `AGENTS.md:17` ("Dependencies flow inward:
domain semantics and contracts, provider adapters, shared application workflows, then CLI/MCP adapters") [F].
A boundary checker exists (`scripts/verify-module-boundaries.mjs`, `npm run verify:module-boundaries`;
`scripts/verify/architecture-guards.mjs`) [F; not executed].

```mermaid
graph TD
  D["scripts/rea.mjs dispatcher"] --> M["src/main.ts MCP adapter (stdio; HTTP opt-in)"]
  D --> C["src/cli.ts + src/cli/ (Incur CLI)"]
  M --> S["src/server/ createServer, register*Tools, ToolResultDelivery"]
  C --> A["src/application/ shared CLI/MCP workflows"]
  S --> A
  S --> K["src/contracts/ TOOL_CONTRACTS, TOOL_EFFECTS, prompts"]
  M --> P["src/composition/ provider + session factories"]
  P --> B["BinarySession + AnalysisProviderRegistry (application/binary)"]
  B --> H["src/hopper → bridge/hopper_bridge.py"]
  B --> G["src/ghidra → bridge/ghidra/ReaGhidraBridge.java"]
  B --> I["src/ida → external ida-pro-mcp"]
  A --> J["src/artifacts, src/javascript, src/browser, src/dotnet, src/android, ... (≈45 format/provider dirs)"]
  A --> R["Reconstruction: ledger / coverage / verification (application + domain)"]
  J --> PR["src/process/ owned process groups, deadlines, cleanup; src/windows Job Objects"]
  A --> DO["src/domain/ pure: Evidence, bundles, unknowns, comparisons (867 files)"]
```

Size by directory (tracked files): `src/domain` 867, `src/application` 454, `src/browser` 170, `src/server` 129,
`src/process` 116, `src/native` 107, `src/artifacts` 106, `src/contracts` 101, `src/ghidra` 83, `src/cli` 64,
then about 40 smaller provider/format directories [F].

Tech stack and pinned runtime dependencies (`package.json`) [F]: Node `^22.19.0 || ^24.11.0 || >=26.0.0`,
`npm@11.16.0`; every runtime dependency is pinned to an exact version, including
`@modelcontextprotocol/server` and `client` 2.3.1, `zod` 4.4.3, `@babel/parser` 8.0.4, `playwright-core` 1.58.2,
`@lydell/node-pty` 1.1.0, `pino` 10.4.0, `incur` 0.6.1 (CLI framework), `isomorphic-git` 1.38.7, `openpgp` 6.3.2,
`evmole` 0.9.3, `tokenx` 1.3.0 (token estimation); optional `frida` 17.23.2. Build tooling: Turborepo, Vitest,
Stryker (mutation), oxlint/oxfmt, knip, jscpd, release-please, husky.

External tools (all bring-your-own except Hopper, which setup may install after approval): Hopper, Ghidra 12.1.x +
JDK 21, IDA via `mrexodia/ida-pro-mcp`, JEB, Kuna, Rizin 0.7.4, GNU objdump, GDB/pwndbg, pwntools, JADX, Apktool,
adb, Binwalk/Unblob, TShark/capinfos, sigrok-cli 0.7.2, WABT 1.0.42, mitmproxy, Chrome-family browser
(`README.md:183-217`, `.agents/skills/reverse-engineer-anything/SKILL.md:71-75`) [F as documented requirements].
Five git submodules pin upstream sources (`.gitmodules`: jadx-headless-mcp, binwalk, unblob, ghidra-nativeaot,
wakaru) [F; not fetched].

Models: REA itself calls **no LLM** [I, no model client dependency in `package.json`; the only model use found is
the optional Codex CLI evaluation harness, §7]. Transport: stdio by default; streamable HTTP via `rea mcp --http`,
bound to `127.0.0.1` by default (`src/config/mcpHttpEndpoint.ts:9-10`) [F].

Startup design detail: when the full output catalog and stdio are used, `src/main.ts:88-114` takes a "deferred"
path that serves a **pre-recorded tool catalog** (`dist/mcp-catalog*.json`) whose SHA-256 must match a value
compiled into the build before it is trusted (`src/main/deferredRuntime.ts:25-46`), and only materializes the
real server on first use; otherwise `runEager` builds the session and transport immediately
(`src/main/eagerRuntime.ts:24-70`) [F].

## 3. Agents

REA defines **no runtime agents or sub-agents** and spawns none [F: no agent definitions; no model client].

| Agent-like artifact | File | Purpose | Tools/permissions | Model | I/O |
|---|---|---|---|---|---|
| Host agent (external) | n/a | Drives the investigation, calls REA tools, writes the reimplementation | Whatever the host grants; REA "does not require permission grants or per-call approval flags" (`SKILL.md:391-395`) | Host's | MCP tool calls → Evidence results |
| Codex CLI as evaluated agent | `scripts/lib/agent-evaluation-commands.mjs:77-97` | Runs scripted investigation prompts against REA for release evaluation | `codex exec --ephemeral --sandbox read-only`, `approval_policy="never"`, per-tool `approval_mode="approve"` allow-list | `REA_AGENT_EVAL_MODEL` or Codex default | JSONL transcript → `evaluateCodexEvents` metrics |
| `openai.yaml` interface stubs | `.agents/skills/rea-analysis-optimization/agents/openai.yaml`, `.agents/skills/rea-ci-tests-audit/agents/openai.yaml` | Codex skill UI metadata (display name, default prompt) | none | none | none |

The product skill does tell the host agent how to parallelize: "When parallel workers are available and the
questions do not depend on one another, assign distinct scopes, point workers to existing evidence, and ask them to
return sources, conclusions, and unresolved gaps" (`SKILL.md:419-422`) [F]. That is advice, not mechanism.

## 4. Skills, commands and prompts

### Skills (`.agents/skills/`, source of truth; built into the ignored `skills/` output, `AGENTS.md:73`)

| Skill | File | Trigger (description) | What it does / notable structure |
|---|---|---|---|
| `reverse-engineer-anything` (v "45") | `.agents/skills/reverse-engineer-anything/SKILL.md` (451 lines) + 6 references (≈1,150 lines) | Native, managed, Electron/JS, packaged, firmware and browser targets; "Skip REA for ordinary source-repository architecture analysis" (`:3`) | Product skill installed into each agent by `rea setup`. Sections: connect only when needed with a 4-step diagnose → dry-run plan → approved apply → restart flow (`:16-69`); a long **target router** mapping each input kind to its first tool (`:94-344`); "work summary-first" token discipline with retained `parent_evidence_id` views (`:346-384`); epistemic rule "distinguish observations, inferences, and unknowns… never imply that static analysis observed execution" (`:386-389`); a 7-step plan for broad investigations ending in a finding ledger and checklist re-check (`:397-430`); progressive disclosure to references (`:432-444`). |
| `rea-analysis-optimization` | `.agents/skills/rea-analysis-optimization/SKILL.md` (113 lines) + Kuna case study | Maintainer: optimize providers for tokens, latency, CPU, memory | Requires an independent correctness oracle, measure-first, table of "observed cost → candidate correction → condition to establish" (`:21-58`). |
| `rea-ci-tests-audit` | `.agents/skills/rea-ci-tests-audit/SKILL.md` (112 lines) + measurement reference | Maintainer: CI/test correctness, false passes, cost | Audit workflow; outcome may be "an explicit decision to stop". |
| `rea-changelog-update` | `.agents/skills/rea-changelog-update/SKILL.md` (134 lines) | Maintainer: release notes from pinned git history | Release Please synchronization and contributor attribution. |
| `rea-tool-design` | `.agents/skills/rea-tool-design/SKILL.md` (20 lines) | Maintainer: design CLI/MCP contracts | Thin pointer to `docs/tool-design.md`. |

### MCP prompts (`src/contracts/promptContracts.ts`, 6 entries; `docs/mcp-prompts.md:8-20`) [F]

`investigate_feature`, `compare_application_versions`, `verify_reconstruction`, `trace_crash`,
`audit_residual_unknowns`, `prepare_bounded_process_capture`. They render optional starting tool suggestions; prompt
arguments and completion values are "rendered as untrusted selection data, not instructions or authorization"
(`docs/mcp-prompts.md:22-27`) [C for the rendering; the contract file exists]. Session-aware argument completion
reads only already-ready provider state and is capped at 100 values (`docs/mcp-prompts.md:60-110`) [C].

### Tools and CLI commands

220 MCP tools are declared in the effect table `TOOL_EFFECTS` (`src/contracts/toolEffects.ts:55-728`, 220 keys) [F, counted].
Each public tool has one `ToolContract` (name, title, description, kind, Zod input/output schema, effects, MCP
annotations, `returnsTargetContent`, validated examples) (`src/contracts/toolContractTypes.ts:43-68`) [F]. MCP
annotations are "derived only from canonical effects" (`toolEffects.ts:24-31`) [F]. CLI and MCP share application
workflows; the CLI is generated from `src/cli/` with Incur. A complete generated catalog is produced by
`npm run docs:generate` (`docs/mcp-contracts.md:1185-1196`) [C; not run].

Reconstruction-relevant tools [F, `src/contracts/applicationToolContracts.ts:81-240`, `sessionToolContracts.ts:136-170`]:
`trace_application_feature`, `trace_javascript_semantics`, `compare_application_versions`,
`compare_source_to_bundle`, `compare_javascript_export_shapes`, `build_reconstruction_obligation_ledger`,
`evaluate_reconstruction_coverage`, `verify_reconstruction`, `correlate_static_and_runtime`,
`list_unknowns`/`record_unknown`/`update_unknown`/`verify_unknown_resolution`, `get_evidence_bundle`,
`export_evidence_bundle`, `capture_process_scenario`, `compare_process_captures`.

## 5. Orchestration and execution workflows

**Execution model.** Hybrid at the system level, but cleanly split: the investigation plan, tool selection and
reimplementation are LLM-driven by the host agent; every REA tool is deterministic code with strict schemas,
canonical ordering ("Registration order never affects selection or caller-visible output",
`src/application/binary/AnalysisProviderRegistry.ts:101-103`, sort at `:166-176`) and content-addressed outputs [F].
The roadmap and tool-design guide explicitly reject an orchestration layer inside REA: "Agents compose experiments
using ordinary commands, scripts, and fixture servers; custom orchestration needs a demonstrated requirement"
(`docs/roadmap.md:24-25`; `docs/tool-design.md:40-44`) [F].

**Concurrency.** Session-scoped admission serializes operations against the bound target
(`src/server/analysisAdmission.ts`, `BinarySession.withAdmittedAnalysis`); external-command tools go through
`runWithExternalMutationAdmission`, which retires the analysis session when a command may have changed the bound
artifact (`src/server/externalMutationAdmission.ts:14-60`) [F]. Provider discovery/startup uses shared in-flight
attempts (`AnalysisProviderRegistry.ts:110-117`) [F]. No parallel agent work is orchestrated by REA [F].

**Retries, recovery, failure handling.** Errors are a tagged error algebra with `Result` values
(`AGENTS.md:31`; `src/domain/result.js` imports throughout) [F]. Cleanup failures keep ownership and are retried
(`AnalysisProviderRegistry.ts:205-240`; `AGENTS.md:19-27`) [F]. Startup causes are redacted from caller-visible
output (`src/main.ts:116-133`) [F]. The skill encodes agent-side retry rules: retry an MCP call once only when safe
to repeat or known not to have started, never repeat an unchanged startup failure, then ask the user to restart the
client (`SKILL.md:33-42`) [F].

**Human approval gates.** `rea setup` shows a plan and requires approval before writing client configuration or
installing Hopper (`src/application/Setup.ts:255-290`: `dryRun`, `approved`, interactive `confirm`) [F]. Analysis
tools have no REA-side approval; the host client's approval policy is the gate (`SKILL.md:391-395`) [F].
Contribution policy requires a human to own and declare every PR ready (`AGENTS.md:94-112`;
`.github/pull_request_template.md`; `.github/workflows/pr-readiness.yml`) [F].

### Traced path 1 — MCP `analyze_javascript_application` (static JS/Electron analysis)

1. `scripts/rea.mjs:15,67` routes `rea mcp` to `dist/mcp/main.js` → `runEntrypoint` → `run`
   (`src/main.ts:88-133`), which parses config from a snapshot of the environment and chooses the deferred or eager
   runtime [F].
2. `runEager` (`src/main/eagerRuntime.ts:24-70`) creates the `BinarySession` via `createBinarySession`
   (`src/composition/binary.ts:26-70`, wiring Hopper/Ghidra/IDA/Kuna providers into an `AnalysisProviderRegistry`)
   and starts the transport with a `ToolResultDelivery` bounded by `REA_MCP_MAX_RESPONSE_BYTES` [F].
3. `createServer` (`src/server/createServer.ts:360-420`) constructs every format service and an
   `EvidenceMcpServer` whose `instructions` concatenate target, recovery and **untrusted-content** guidance
   (`createServer.ts:326-355`) [F].
4. `registerElectronTools` registers the tool (`src/server/registerElectronTools.ts:110-138`); with
   `detail: "summary"` it first checks that analysis-view retention is available [F].
5. `analyzeJavaScriptApplicationValidated` (`src/application/javascript/JavaScriptApplicationService.ts:57-150`)
   runs phases with progress reports and cancellation checkpoints: `reconstructJavaScriptArtifact`
   (`JavaScriptArtifactReconstruction.ts:82-102`, inside an `ArtifactResourceScope`) → `completeJavaScriptAnalysisSteps`
   → `createOwnedJavaScriptApplicationEvidenceCooperatively` → an `Evidence` record [F].
6. Back in the handler, summary mode calls `projectRetainedAnalysis` to return a small view while the complete
   record is retained; `runElectronTool` records Evidence into the session ledger (`registerElectronTools.ts:194-235`)
   and `ToolResultDelivery` encodes the result, adding `_meta.provenance.untrusted_content` when the contract
   `returnsTargetContent` (`src/server/ToolResultDelivery.ts:106-250`; `src/server/toolResultEncoding.ts:29-37`) [F].
7. Output/state: an `ev_<sha256>` Evidence record in the session ledger, retrievable by `inspect_analysis_view`,
   `get_evidence_bundle` and `export_evidence_bundle` [F].

### Traced path 2 — `build_reconstruction_obligation_ledger` (parity closure)

1. CLI `rea build-reconstruction-obligation-ledger '<json>' --json` or MCP tool of the same name
   (`docs/reconstruction-obligation-ledgers.md:6-10`) [C for the CLI; the MCP registration is F].
2. MCP: `registerReconstructionObligationLedgerTool` (`src/server/registerApplicationTools/obligationLedger.ts:20-62`)
   runs under `runAdmittedToolOperation`, parses input with `resolveReconstructionObligationLedgerRequest`
   (Zod schema, `src/application/ReconstructionObligationLedgerService.ts:30-37`) [F].
3. `buildReconstructionObligationLedgerEvidenceValidated` (`ReconstructionObligationLedgerService.ts:40-72`) calls
   `deriveReconstructionObligationCandidates` (static Application Graph and process-capture records become
   conservative candidates, plus caller-reviewed obligations) and then `evaluateReconstructionObligationLedger` [F].
4. `evaluateReconstructionObligationLedger` (`ReconstructionObligationLedgerEvaluation.ts:53-114`) re-parses and
   authenticates the bundle, sorts candidates by code point, and for each obligation (`:173-245`) adds diagnostics
   for duplicate definition, missing/ambiguous owner, missing parser type, missing case kind, weak fixture
   authority, missing verifier, verifier that does not enumerate the obligation, absent result Evidence,
   contradictions, residual unknowns and unavailable authority; then dependency diagnostics, ownership and dependency
   graphs, summary buckets, a `closure_digest`, and a `ledger_id` digest over Evidence IDs + obligation IDs +
   closure digest [F].
5. Authority comparison (`src/application/ReconstructionObligationAuthority.ts:15-108`): fixture/verifier proof
   must be `observed` Evidence with predicate `rea.reconstruction-proof`, operation
   `verify_reconstruction_obligations`, `passed === true`, and IDs that enumerate the obligation, fixture, case,
   verifier and claim; a proof authority satisfies a requirement only through a fixed lattice (e.g. `native-abi`
   only by `native-abi`; `packaged-process` by `packaged-process` or `live-observation`) [F].
6. Output: one Evidence record (`predicate_type: rea.reconstruction-obligation-ledger`, `confidence: inferred`,
   `authority: analyst-inference`) wrapping the full ledger (`ReconstructionObligationLedgerService.ts:74-93`), and
   the input bundle's records are recorded into the session (`obligationLedger.ts:49-54`) [F].

Finding on path 2: no non-test code in `src/` or `scripts/` produces Evidence with predicate
`rea.reconstruction-proof`; the only producer is `src/application/ReconstructionObligationLedger.fixture.ts:70-71`
[F, repository-wide grep]. Closure therefore depends on proof records supplied by the caller's own verifier
harness, wrapped in REA's Evidence format [I].

### Traced path 3 (abbreviated) — `open_binary` on a native target

`registerSessionTools.ts:284-305` → `session.open(path, …)` (`src/application/binary/BinarySession.ts`, transition
methods `#openWithinTransition`, `#restoreAfterFailedOpen`) → `AnalysisProviderRegistry` selects one deep provider
deterministically, "no fallback" (`docs/architecture.mermaid`; registry `:101-176`) → e.g. `GhidraProvider` →
`GhidraLauncher`/`GhidraTransport` → packaged `bridge/ghidra/ReaGhidraBridge.java` HeadlessScript in an isolated
temporary project (`SECURITY.md:38-45`) [F for files and call sites; runtime behaviour Unverified (not executed)].

## 6. Context and state management

- **Evidence model** (`src/domain/evidence.ts:117-150`) [F]: strict record with `subject` (target digest),
  `provider`, `analysis_profile`, `predicate_type`, `operation`, `parameters`, `raw_result`, `normalized_result`,
  `confidence` (`observed|derived|inferred`), `authority` (`shipped-artifact|controlled-replay|
  historical-reference|external-service|analyst-inference`), `environment` (with `isolation:
  none|process|container|virtual-machine`), `limitations`, `relationship_coverage`, `locations`, `evidence_links`.
  `evidence_id` is `ev_` + a canonical digest of the record's semantic projection (`:283`), and parsing an
  "authenticated" record recomputes it (`:176-189`) [F].
- **"Authentication" is integrity, not provenance** [I from F]: bundle authentication re-parses each record,
  rejects duplicates, validates the unknown graph and requires canonical JSON (`src/domain/evidenceBundle.ts:304-340`);
  there is no key, HMAC or signature over Evidence (repository grep for `createHmac|createSign(` finds only
  `src/cutter/CutterBridgeClient.ts`). A caller can therefore construct a well-formed `observed` /
  `controlled-replay` record with a matching ID. The ledger's guarantees hold relative to the honesty of whoever
  produced the bundle.
- **Session ledger and retention**: Evidence is recorded per session; summary-first delivery returns small views
  and keeps a `parent_evidence_id` for paging via `inspect_analysis_view`; `get_evidence_bundle` supports
  `detail: "summary"` with exact filters; `export_evidence_bundle` writes the whole session to a caller path
  (`SKILL.md:346-376`; `sessionToolContracts.ts:166-170`) [F for contracts].
- **Residual unknowns**: a first-class registry with deterministic IDs, immutable revisions and optimistic
  concurrency ("Requires exact expected_revision; stale concurrent writers fail") (`sessionToolContracts.ts:146-165`)
  [F]. Closing a binary clears its ledger and unknown registry (`docs/mcp-prompts.md:124-128`) [C].
- **Snapshots and caches**: `BinarySessionRecords + AnalysisSnapshotCache` hold per-target/profile snapshots
  (`docs/architecture.mermaid`); `AGENTS.md:48-52` requires cache keys to cover all result-affecting inputs and
  freshness checks before reporting cached live state [F as policy; cache code not read in depth].
- **Handoff artifacts**: portable Evidence bundles (JSON) are the handoff between sessions, between CLI and MCP
  (parity is asserted in `scripts/verify-reconstruction-readiness.mjs:61-80` — identical `evidence_id` from CLI and
  MCP for the same input), and between "original" and "reconstruction" in the ledger [F].
- **Resumability**: a later session can import an exported bundle (`rea inspect-evidence-bundle`, `SKILL.md:373-376`)
  [C]. No conversation memory or agent state is persisted by REA [F: none found].
- **Context built for the agent**: server `instructions` (`createServer.ts:339-343`), the skill, and compact input
  schemas by default (`REA_MCP_INPUT_SCHEMA_PROFILE`, `README.md:92-97`; `src/contracts/compactInputSchema.ts`) [F].

## 7. Engineering practices and testing

- **Tests** [F, counted]: 2,081 `*.test.*` files, 2,080 of them Vitest (the other is
  `scripts/fixtures/http3-lab.test.py`), concentrated in `tests/boundary` (956), `src/domain`
  (303), `tests/acceptance` (181), `src/application` (141), `tests/process-global` (58), `tests/conformance` (26);
  about 16 Python test files, mostly experiment oracles: 3 under `bridge/` (mitmproxy, native, pwndbg), 10 in
  `experiments/analysis-efficiency/`, the rest in `tests/fixtures/` and `scripts/`. `docs/testing.md` (1,909 lines) defines a test-design hierarchy — real public
  CLI/MCP workflows, then production-boundary integration, then producer goldens (`AGENTS.md:79-81`) — and dedicated
  lifecycle regressions (late handshakes, cancellation during cleanup, cleanup retry; `AGENTS.md:23`,
  `docs/testing.md:311-450`) [F as docs].
- **Real-toolchain lanes**: about 100 `verify:*` npm scripts, each proving one provider/host claim against the real
  engine (Ghidra per architecture, Hopper, IDA, Kuna, JEB, browser, Electron, Frida, pcap, firmware, Android, and a
  `verify:<client>` script per agent client) (`package.json` scripts; `docs/testing.md:746-911`) [F that they exist;
  not executed]. About 20 `real-*.yml` workflows run a subset in CI (`.github/workflows/`) [F].
- **Conformance/readiness**: `npm run verify:readiness` builds native fixtures, analyzes JS CLI and Electron fixtures
  through both CLI and MCP, evaluates a nine-stage readiness report and checks rejection of stale or tampered replay;
  CI runs it on Linux and uploads the report (`docs/reconstruction-readiness.md:1-31`; `.github/workflows/ci.yml:796`)
  [F for wiring]. Stages are fail-closed: `fail`, `unknown`, `unsupported`, `truncated`, `skipped` never aggregate to
  `pass` (`docs/reconstruction-readiness.md:48-50`) [C, evaluator code at `src/domain/reconstructionReadiness*.ts`
  exists but was skimmed only].
- **Mutation testing**: Stryker on the reverse-tools subset, nightly cron (`.github/workflows/mutation.yml:4-5`);
  `thresholds: { break: null }` so it never fails the build (`stryker.config.mjs:20`) [F].
- **Static checks**: TypeScript strict (`tsconfig.json`), oxlint, oxfmt, knip (dead code), jscpd (duplication),
  dependency check, module-boundary verifier, generated-docs check; `check:fast` on pre-push via husky
  (`AGENTS.md:60-69`, `.husky/pre-push`) [F].
- **CI**: `ci.yml` has scheduled "full qualification" runs hourly plus a forced full run daily
  (`ci.yml:8-10,111-120`), Linux/macOS/Windows jobs, all third-party actions pinned to commit SHAs (repo-wide 59
  `actions/checkout@` and 50 `actions/setup-node@` uses, 16 each in `ci.yml`, and others) [F]. Current health: see §1 (bulk-merge failures/cancellations) [F].
- **Agent evals of the tool surface itself**: `npm run verify:agent` runs ~10 scripted investigation prompts
  through a real Codex CLI (`scripts/verify-agent-experience.mjs:148-262`) in an isolated `CODEX_HOME` with
  `sandbox_mode = "read-only"`, web search off, history off (`:103`). `evaluateCodexEvents`
  (`src/evaluation/CodexAgentEval.ts:136-245`) scores: natural use, correct first tool, repeated identical calls,
  input-validation failures, required ordered tool subsequence, token usage (input/cached/output), whether the final
  answer cites a returned Evidence ID, answer-term coverage, an epistemic-cue regex, and a **known-answer factual
  check** against fixture claims (`src/evaluation/KnownAnswerEvaluation.ts`) [F]. It is not wired into any workflow
  (no `.github/workflows` file references `verify:agent`) and needs local Codex authentication [F].
- **Independent verification of produced software**: REA does not build software; its reconstruction tools require
  that a reimplementation be verified by a verifier at an authority comparable to the original observation, with a
  green unit test explicitly unable to close a `packaged-process` obligation
  (`docs/reconstruction-obligation-ledgers.md:318-322`; lattice at `ReconstructionObligationAuthority.ts:29-61`) [F].

## 8. Security, isolation and observability

- **Permission model**: REA has no per-call permission flags; it relies on the host client's approval policy
  (`SKILL.md:391-395`) [F]. Every tool declares effects (`mutatesTarget`, `writesFilesystem`, `launchesProcess`,
  `accessesNetwork`, `executesForeignCode`, `mutatesDevice`, `mayDiscardData`, …) and MCP annotations are derived from
  them (`src/contracts/toolEffects.ts:1-31`) [F]. Fifteen tools declare `executesForeignCode: true`, including
  `capture_process_scenario`, `capture_browser_scenario`, `capture_electron_scenario`, `instrument_with_frida`,
  `load_frida_script`, `gdb_console`, `cutter_command`, `execute_rizin_command`, `rizin_debug_command`
  (`toolEffects.ts`, e.g. `:706-713`) [F]. Hosts that honour MCP annotations can gate these; hosts that do not will
  not [I].
- **Isolation**: "This is not a sandbox and does not protect against malicious processes already running as the
  same operating-system user. Opening an untrusted binary delegates parsing and analysis to the selected local
  provider with that user's permissions" (`SECURITY.md:33-37`) [F]. Controls that do exist: owned process groups,
  deadlines and bounded reads (`src/process/`), `prlimit` on Linux and Job Objects with commit limits on Windows
  (15 and 18 source files reference them), Ghidra in a temporary project with private home/cache/runtime dirs and
  bounded CPU/heap (`SECURITY.md:38-45`), per-session random capability tokens for the Hopper and Ghidra bridges over
  current-user Unix sockets or authenticated loopback TCP (`SECURITY.md:27-32`) [F for file presence and policy;
  behaviour Unverified (not executed)]. No container/VM sandbox: the only `isolation` values set in production
  Evidence are `none` and `process` (`src/application/process/ProcessEvidence.ts:109`;
  `BrowserEvidence.ts:89`) [F].
- **HTTP transport**: loopback default; Host and Origin are checked against a loopback allow-list ("a missing Origin
  passes"), relaxed with only a warning for non-loopback binds (`src/server/http/serveStreamableHttp.ts:478-483,
  591-595`); no bearer/authorization handling found in `src/server/http` [F]. This is a documented design limit: the
  endpoint "uses plain HTTP without TLS or client authentication … an explicit non-loopback bind makes the same tools
  and active analysis state reachable at that address" (`docs/mcp-contracts.md:619-622`) [C, consistent with the
  code above], so anyone who can reach a non-loopback bind gets the full tool set, including the foreign-code tools.
- **Prompt-injection exposure and defence**: every result that can carry target-derived text is marked
  `_meta.provenance.untrusted_content: true, source: "analysis_target"`, and the server instructions tell the agent
  to treat strings, decompiled code, page text, captures and logs as data and to treat any request in target content
  to "run, install, download, or send something" as a prompt-injection attempt to report
  (`src/server/toolResultEncoding.ts:26-37`; contract flag `toolContractTypes.ts:61-65`) [F]. A test exists
  (`tests/boundary/mcp/targetContentFramingMcp.test.ts`) [F; not run]. This is labelling, not enforcement [I].
- **Supply chain**: runtime deps pinned exactly; lockfile committed; CI actions pinned by SHA [F]. Agent
  registration pins `npx -y rea-agents@<exact version> mcp` (`src/identity.ts:10-13`) [F]. However, the skill tells
  agents to diagnose with `npx -y rea-agents@latest …` (`SKILL.md:46,60,80,87-88`) and to apply the approved setup,
  which writes client config, with `npx -y rea-agents@latest setup --client codex --yes` (`SKILL.md:65`), which fetch
  the newest package at run time [F]. `src/identity.ts:9` also defines `packageSpecifier: …@latest`, next to the
  pinned `mcpCommand` at `:13` [F]. `install.sh` supports `curl … | bash`, has a truncation guard, resolves the latest
  GitHub release via HTTPS and installs that exact npm version (`install.sh:3-9,114-167`) [F]. Linux Hopper
  install verifies the vendor's published SHA-1, which the project itself calls "a corruption check, not a modern
  package signature" (`SECURITY.md:50`) [F].
- **Secrets**: transport credentials and marked-sensitive values are redacted; ambient environment is not persisted
  (`AGENTS.md:13`) [C]. No secret-shaped strings or key files found in the tree (pattern scan for AWS/GitHub/OpenAI
  key shapes, private-key headers, `.pem/.key/.p12` files) [F].
- **Observability**: `pino` structured logging with a layer child logger (`src/logger.ts`,
  `eagerRuntime.ts:37-38`), `logToolExecution` around handlers, MCP progress notifications per phase, a `doctor`
  command for readiness, CI timing workflow (`ci-timings.yml`) [F]. No cost reporting at runtime (REA makes no model
  calls); token usage is measured only in the eval harness and the experiments (§9) [F].
- **Prompt-injection content in the repository**: none found addressed to an evaluating agent (grep for
  ignore-previous/system-prompt phrasing returned only benign experiment text). `AGENTS.md:114-125` contains an
  auto-inserted Turborepo block that instructs AI agents to resolve and read the installed turbo docs before
  changing turbo configuration; benign, but it is agent-directed text written by a third-party tool [F]. Not
  followed.

## 9. Efficiency

- Explicit priority order for all work: agent tokens and context first, then analysis time, then CPU/memory
  (`AGENTS.md:35-58`), with a requirement to measure "representative completed tasks", separate cold and warm runs,
  and report token usage, elapsed time, CPU time and peak memory; "Fewer bytes alone do not establish fewer tokens"
  [F as policy].
- Mechanisms [F]: compact input schemas by default; optional output-schema omission
  (`REA_MCP_OUTPUT_SCHEMA_PROFILE`); deferred startup with a digest-verified recorded catalog; summary-first results
  with retained parent Evidence and paged views; per-response byte cap (`REA_MCP_MAX_RESPONSE_BYTES`) with
  `resource_constraint` guidance to page rather than re-run (`SKILL.md:360-366`); shared in-flight provider startup;
  analysis snapshot cache.
- Measurement record: `experiments/analysis-efficiency/` (191 files) holds dated checkpoints per optimization
  (native inventory views, Ghidra evidence projection, GGUF validation, WAT framing, Apktool string tables,
  retained-capture validation, SAZ selection…), several recording **negative or unchanged** token and timing results
  (`experiments/analysis-efficiency/README.md:1-60`) and a 2026-10-21 coverage reconciliation across 46 source
  directories [F for files; results not reproduced].
- Model routing: none inside REA; the eval harness can select a Codex model (`REA_AGENT_EVAL_MODEL`) [F].
- Operational overhead: heavy. Deep native analysis needs licensed or large external engines; Ghidra default cold
  startup deadline is 330 s (`SKILL.md:340-344`); the Linux `ps`/procps and `prlimit` prerequisites are
  host-specific (`README.md:70-74`) [F].

## 10. Continuous improvement

- No runtime self-improvement, learning capture or memory of lessons inside REA [F: none found].
- Developer-side loops [F]: the agent-experience evaluation (§7) measures how real agents route and how many tokens
  they spend, giving a feedback signal for tool descriptions and schemas; `docs/tool-design.md:186-194` requires
  evaluating "representative broad, direct, and negative tasks on the intended host" when discoverability changes,
  and records "Schema validity and keyword heuristics do not establish successful tool selection".
- Maintainer skills encode improvement procedures (analysis optimization with an independent oracle; CI/test audit;
  changelog). Branch names show heavy agent-driven development (29 `codex/…`, 14 `cursor/…`, 4 `agent/…`,
  4 `audit/…` branches out of 181, e.g. `codex/bug-sweep-20261015`) [F names only; I that agents author much of the
  code]. `AGENTS.md:83-112` sets issue and PR rules for AI-assisted contributions (report only checks that actually
  ran; a human declares readiness) [F].

## 11. Reference-driven development and reverse engineering

This is REA's core purpose; it is the most complete implementation of this theme among typical agent tooling
[I]. Components:

1. **Specification extraction from shipped artifacts** [F]: format-aware extractors build an Application Graph for
   JavaScript/Electron (modules, imports, source maps, routes, IPC, preload bridges, native add-ons;
   `trace_application_feature`, `trace_javascript_semantics`), mobile application graphs
   (`project_android_application_graph`, `project_apple_application_graph`, `project_harmony_application_graph`),
   managed (.NET) member inventories and a `ManagedReconstructionService`
   (`src/application/managed/ManagedReconstructionService.ts`), and native function dossiers, pseudocode, CFG and
   references via the deep providers. Static candidates are kept separate from runtime proof throughout.
2. **Feature parity / difference measurement** [F]:
   - `compare_application_versions`: two Application Graphs, unique-only exact digest / source digest /
     source-map / structural-fingerprint / semantic-key tiers, reporting added/removed/changed/ambiguous/unknown
     "without fuzzy or module-ordinal pairing" (`applicationToolContracts.ts:126-150`).
   - `compare_source_to_bundle`: a committed historical source graph versus a shipped bundle, classifying
     unchanged/modified/removed/split/merged/duplicated/unknown with explicit weighted signals; "incomplete coverage
     and ambiguous weak signals never become absence or forced matches" (`:153-167`).
   - `compare_javascript_export_shapes`: static return-shape diffs as JSON Pointer changes, with runtime semantics
     left to "a separate agent-run probe" (`:169-195`).
   - Process capture comparison under an explicit concurrency model — `finite_traces` languages or a
     `partial-order` graph (`src/domain/process/processTraceSpecification.ts:90-130,625`); the readiness verifier
     fails a run that uses total-order comparison for concurrent behaviour (`docs/reconstruction-readiness.md:59`).
3. **Reconstruction verification** [F]:
   - `verify_reconstruction`: "Verify a finite typed behavioral and structural specification against a canonical
     Evidence bundle. Pass means every declared claim has complete comparable authority—not global source
     equivalence" (`sessionToolContracts.ts:141-145`; `src/domain/reconstructionVerification.ts:48-49`).
   - `build_reconstruction_obligation_ledger`: per-obligation closure requires a unique owner (module path, symbol,
     implementation SHA-256), parser/schema/domain type when required, original cases and reconstruction fixtures
     for every required case kind (positive, negative, malformed, cancellation, teardown…), and a passing verifier
     that enumerates the obligation, at a comparable authority; blocked/out-of-scope dispositions are recorded and
     never counted as verified (`docs/reconstruction-obligation-ledgers.md:10-20,226-322`; §5 path 2).
   - `evaluate_reconstruction_coverage`: per named boundary; package/clean-install/runtime-routing claims need
     observed runtime Evidence; "an inference alone establishes neither a passing nor a failed package workflow"
     (`docs/reconstruction-coverage.md:34-43`).
   - Residual-unknown registry with evidence-qualified resolution (`verify_unknown_resolution`).
4. **Visual / runtime verification** [F for tools; behaviour Unverified (not executed)]: Chrome-family browser
   observation and declared-action scenarios with requested screenshots (`capture_browser_scenario`,
   `README.md:202`), Electron main/renderer capture, native UI scenario capture on macOS
   (`capture_native_ui_scenario`, `bridge/native/ReaNativeUI.swift`), PTY process capture with run comparison
   (`README.md:216`), passive V8 Inspector capture.
5. **Worked examples** [C]: the README showcases a DX-Ball reconstruction that "passes 3,205 original-x86 cases and
   reproduces all 63 compiled function bytes" and a TH04 16-bit recovery compared against "historical compiler
   output", both with external reconstruction repositories (`README.md:246-270`). Not verified here.

Boundary of the capability [F/I]: REA proves *claims about artifacts and reconstructions given Evidence*; it does
not itself generate a specification document, plan the reimplementation, write code, or run the reimplementation's
tests — those remain the host agent's job. And because Evidence integrity is a content digest without a signing
key (§6), the ledger cannot distinguish an honest verifier record from a fabricated one [I].

## 12. Innovations

1. **Authority-typed, content-addressed Evidence** used uniformly across 220 tools, CLI and MCP, with
   `confidence` and `authority` as separate axes and "unknown is not absence" enforced in schemas
   (`src/domain/evidence.ts:117-150,283`; `docs/tool-design.md:46-66`) [F].
2. **Fail-closed reconstruction obligation ledger** with an explicit proof-authority lattice and per-case-kind
   fixture requirements; deterministic `ledger_id`/`closure_digest` (`ReconstructionObligationAuthority.ts:15-61`;
   `ReconstructionObligationLedgerEvaluation.ts:53-114`) [F]. This is a reusable formalism for "feature parity is
   proven, not asserted".
3. **Partial-order / finite-trace comparison of concurrent behaviour** instead of naive total-order diffs
   (`processTraceSpecification.ts`) [F].
4. **Untrusted-content provenance marker** on every tool result that may carry target text, plus server-level
   instructions (`toolResultEncoding.ts:26-37`) [F].
5. **Effect declarations as the single source for MCP annotations** — `executesForeignCode`, `mayDiscardData`,
   `mutatesDevice` etc. audited per tool (`toolEffects.ts`) [F].
6. **Digest-verified recorded tool catalog** for fast, lazy MCP startup without constructing validators
   (`deferredRuntime.ts:25-46`) [F].
7. **Agent-experience evaluation** that scores real agent transcripts on routing, repetition, validation failures,
   token use, Evidence citation and known-answer correctness (`CodexAgentEval.ts:136-245`) [F].
8. **Measured efficiency culture** with dated, partly negative benchmark checkpoints
   (`experiments/analysis-efficiency/`) [F].

## 13. Reusable components

| Component | Path | Kind | Dependencies | License | Security notes | Reuse class | Limits and compatibility constraints |
|---|---|---|---|---|---|---|---|
| Evidence record + bundle model | `src/domain/evidence.ts`, `src/domain/evidenceBundle.ts`, `src/domain/canonicalDigest.ts` | library / pattern | zod 4, `canonicalize` | MIT | Integrity digest only; no signing — add a key if provenance matters | needs adaptation | Deeply coupled to REA's domain types (`subject`, `analysis_profile`, provider identity) |
| Reconstruction obligation ledger | `src/application/ReconstructionObligation*.ts`, `src/domain/reconstructionObligationLedger*.ts` | library / pattern | Evidence model, zod | MIT | Closure trusts caller-supplied proof records | reimplement the idea (or needs adaptation) | No in-repo producer of `rea.reconstruction-proof`; caller must supply verifier records |
| Proof-authority lattice | `src/application/ReconstructionObligationAuthority.ts:15-108` | pattern | none | MIT | n/a | reimplement the idea | Authority vocabulary is REA-specific |
| Reconstruction coverage + verification + readiness stages | `src/domain/reconstructionCoverage*.ts`, `reconstructionVerification.ts`, `reconstructionReadiness*.ts`, `docs/reconstruction-*.md` | pattern | Evidence model | MIT | Readiness evaluator is internal, not a public tool | reimplement the idea | Nine-stage readiness list is a good checklist; code is not standalone |
| Process trace specification (partial order / finite traces) | `src/domain/process/processTraceSpecification.ts` | library | zod | MIT | n/a | needs adaptation | Bound to REA process-capture observations |
| Untrusted-content result marker | `src/server/toolResultEncoding.ts:26-37`, `toolContractTypes.ts:61-65` | pattern | MCP SDK `_meta` | MIT | Labelling, not enforcement; depends on host honouring it | reimplement the idea | Any MCP server can copy the pattern |
| Tool effects table → MCP annotations | `src/contracts/toolEffects.ts` | pattern | none | MIT | Makes risky tools machine-visible | reimplement the idea | Annotation semantics vary by MCP host |
| Agent-experience eval scorer | `src/evaluation/CodexAgentEval.ts`, `KnownAnswerEvaluation.ts`, `scripts/verify-agent-experience.mjs`, `scripts/lib/agent-evaluation-commands.mjs` | script / library | Codex CLI, local auth | MIT | Runs Codex `--sandbox read-only`, `approval_policy=never` with a tool allow-list | needs adaptation | Parses Codex JSONL specifically; heuristics (regex epistemic cue) are coarse |
| `reverse-engineer-anything` skill | `.agents/skills/reverse-engineer-anything/` | skill | REA MCP server | MIT | Uses `npx -y rea-agents@latest` for diagnosis and the approved setup-apply step | reference only (usable as-is only with REA installed) | 451 lines + references; tightly bound to REA tool names |
| `rea-analysis-optimization` skill | `.agents/skills/rea-analysis-optimization/` | skill | REA docs | MIT | none | reimplement the idea | Its oracle-first, measure-first workflow generalizes |
| Setup planner with dry-run, backups, approval | `src/application/Setup*.ts`, `SetupSkill.ts`, `ClientConfiguration*.ts` | library / workflow | Node fs, `write-file-atomic`, `jsonc-parser`, `smol-toml`, `yaml` | MIT | Additive and idempotent per `AGENTS.md:11`; writes many agents' configs | reference only | Supports ~15 clients; large, product-specific |
| Process ownership/supervision | `src/process/`, `src/windows/`, `native/windows/` | library | Node-API native module on Windows | MIT | Not a sandbox (`SECURITY.md:33`) | reference only | Large and platform-specific |
| REA MCP server as a whole | package `rea-agents` | tool server | Node ≥ 22.19; external engines per target | MIT (+ third-party licenses; commercial tools need user licences) | Foreign-code tools; HTTP mode unauthenticated | directly reusable (as an external tool, not code) | Fast-moving (6 majors in 3 months); main ahead of npm release |

## 14. Evidence against the value dimensions

**Engineering quality.** Demonstrated: strict layering with a boundary verifier, exact dependency pins, SHA-pinned
actions, a typed error algebra, single-source tool contracts with validated examples, 2,081 `*.test.*` files and
about 100 real-toolchain verification scripts (§2, §7). Also demonstrated: main was unstable on the evaluation day
(14 failures and 66 cancellations in the last 100 completed CI runs, a bulk-merge repair commit, §1). Mutation
testing is informational only (§7). Test pass rates and real-lane results were not executed and are unverified.

**Autonomy and orchestration.** Demonstrated: REA intentionally has no orchestration; autonomy lives in the host
agent, steered by a detailed skill, six prompts and server instructions (§3-§5). Deterministic tool behaviour,
canonical ordering and admission/serialization per session are implemented (§5). Parallelism is advice in the skill
only.

**Development productivity.** Claimed: an agent can understand a feature in a binary or app and "build a version
for your project" (§1, §11), with three showcases (§11.5, not verified). Demonstrated: one-command setup across ~15
agent clients with dry-run plans and backups (§5, §8); CLI fallback without MCP (§4). Productivity effects were not
measured here.

**Security and reliability.** Demonstrated: effect declarations per tool; untrusted-content marking; capability
tokens for engine bridges; private temp projects; prlimit/Job Object bounds; loopback-default HTTP with Host/Origin
checks; exact pins (§8). Limits demonstrated in code/docs: no sandbox, 15 tools execute foreign code, no HTTP
authentication (a documented design limit), Evidence integrity without provenance signing, `@latest` in skill
diagnostics and setup apply (§6, §8).

**Maintainability and adaptability.** Demonstrated: clear ownership rules and cleanup invariants in `AGENTS.md`,
provider-neutral contracts, ports between layers (§2). Counter-evidence: very large surface (220 tools, ≈45
provider/format directories, 1,909-line testing guide), six breaking majors in three months, and main documented as
ahead of the npm release (`SKILL.md:21-26`) (§1, §4).

**Resource efficiency.** Demonstrated: token-first optimization policy, compact schemas, summary-first retained
views, response byte caps, lazy catalog startup, and dated measurement checkpoints including negative results (§9).
Runtime costs of external engines (e.g. 330 s Ghidra cold deadline) remain high and were not measured here.

## 15. Strengths and limitations

Strengths
- Rigorous epistemics: observation/derivation/inference/unknown are typed and preserved end to end
  (`evidence.ts:117-150`; `SKILL.md:386-389`).
- Parity is formalized: obligations, case kinds, owners, verifier enumeration and authority lattice
  (`ReconstructionObligationLedgerEvaluation.ts:173-330`; `ReconstructionObligationAuthority.ts`).
- Concurrency-aware behavioural comparison (`processTraceSpecification.ts`).
- Prompt-injection awareness built into the result envelope (`toolResultEncoding.ts:26-37`).
- Breadth of extractors with honest "unknown, not absent" semantics (`README.md:183-217`; `docs/tool-design.md:55-66`).
- Real-engine verification lanes per claim, and agent-transcript evaluation of the tool surface (§7).
- Supply-chain hygiene: exact pins, SHA-pinned actions, version-pinned agent registration (§8).

Limitations
- Not an orchestrator: no planning, spec authoring, implementation or test execution of the reimplementation (§5, §11).
- Evidence "authentication" is a digest; fabricated proof records with correct IDs pass (`evidenceBundle.ts:304-340`, §6).
- No public producer of reconstruction-proof Evidence; ledger closure depends on the caller's harness (§5 path 2).
- No sandbox; foreign-code tools run with the user's permissions (`SECURITY.md:33-37`).
- HTTP transport has no authentication, a design limit the project documents (`docs/mcp-contracts.md:619-622`);
  non-loopback binds relax Host checks with a warning only (`serveStreamableHttp.ts:591-595`).
- Agent-experience eval is not in CI and needs Codex credentials (§7).
- Very high churn and current CI instability on main (§1); main ahead of the published package.
- Deep native analysis needs heavyweight or commercial engines (Hopper/IDA/JEB licences) (§2, `README.md:413-420`).

## 16. Claims vs verified ledger

| Claim (source) | Status | Evidence |
|---|---|---|
| One MCP for reverse engineering across binaries, apps and runtime behaviour (`README.md:8`) | partly | Tool contracts and ~45 provider/format directories exist (§2, §4); runtime behaviour not executed |
| Analysis runs locally (`README.md:63`) | partly | No model client; HTTP binds loopback by default (`mcpHttpEndpoint.ts:9-10`); browser/network tools can access the network (`toolEffects.ts` `accessesNetwork`) |
| Results include evidence and limitations behind each conclusion (`README.md:63`) | verified (design) | Evidence schema has `limitations`, `locations`, `confidence`, `authority` (`evidence.ts:133-150`) |
| Setup shows planned changes and requires approval (`AGENTS.md:11`) | verified (code path) | `Setup.ts:255-290` dry-run / approved / confirm; not executed |
| Registration is version-pinned (`docs` / skill) | verified | `src/identity.ts:10-13` |
| Static JS and .NET inspection do not run the application (`README.md:219-221`) | partly | `analyze_javascript_application` effects do not include `executesForeignCode` (§8); not executed |
| Ledger closes only with comparable verifier authority (`docs/reconstruction-obligation-ledgers.md:12-20`) | verified (code) | `ReconstructionObligationLedgerEvaluation.ts:173-330`; `ReconstructionObligationAuthority.ts:29-90` |
| Evidence IDs and manifests "must authenticate" (`docs/reconstruction-coverage.md:8-12`) | partly | Authentication = canonical digest + shape checks; no cryptographic provenance (`evidenceBundle.ts:304-340`) |
| `verify:readiness` runs in CI on Linux (`docs/reconstruction-readiness.md:24-26`) | verified (wiring) | `.github/workflows/ci.yml:796`; run results not checked |
| Target content is marked untrusted (`docs/mcp-contracts.md`) | verified (code) | `toolResultEncoding.ts:26-37`; delivery uses `returnsTargetContent` in `ToolResultDelivery.ts` |
| Bridges authenticated with per-session random capability tokens (`SECURITY.md:27-32`) | not executable | Not traced into bridge code; not executed |
| Ghidra in isolated temporary project, deleted on close (`SECURITY.md:38-45`) | not executable | Not executed |
| DX-Ball reconstruction passes 3,205 cases and reproduces 63 function bytes (`README.md:249-250`) | not found (external) | Lives in an external repository; not checked |
| "300,000 GitHub stars" (`README.md:372`) | verified as metadata | gh api reports 365,013 stars on 2026-10-22; organic nature unknown |
| Agent release evaluation scores session transcripts (`docs/architecture.mermaid`) | verified (code) | `CodexAgentEval.ts:136-245`; not run; not in CI |
| Mutation testing guards reverse tools (`package.json`) | partly | Nightly Stryker, but `thresholds.break: null` (`stryker.config.mjs:20`) |

## 17. Uncertainties and research completeness

Could not check, and why:
- Any runtime behaviour (tests, real-engine lanes, readiness report, agent eval, setup) — rule: no execution. All
  such statements are marked Unverified (not executed) or [C].
- Bridge internals (`bridge/hopper_bridge.py`, `bridge/ghidra/*.java`, Swift/LLDB tracers) and the capability-token
  handshake — listed but not read in depth.
- Most of the ≈45 format/provider directories (`src/browser`, `src/native`, `src/artifacts`, `src/dotnet`,
  `src/android`, `src/firmware`, `src/gpu`, `src/il2cpp`, `src/evm`, `src/wasm`, `src/sqlite`, etc.), the website,
  `native/windows`, and the 1,909-line `docs/testing.md` beyond headings and two sections — skipped for breadth.
- The readiness evaluator (`src/domain/reconstructionReadiness*.ts`) and `reconstructionCoverageEvaluation.ts` were
  skimmed via docs, not read line by line.
- Submodule contents (not fetched) and the 181 remote branches (names only; none cloned, since releases are cut from
  `main` and no default-branch divergence was found).
- Whether the star/fork counts reflect organic adoption.

Completeness rating: **mostly** — architecture, entry points, contracts, the Evidence model, the full
reconstruction-obligation path, the security envelope, CI, the skill set and the eval harness were read from
source; the long tail of format providers and bridges was skipped.

Approximate coverage: about 45 files read in full or in substantial part (README, AGENTS.md, SECURITY.md,
architecture map, roadmap, 4 reconstruction/prompt docs, tool-design guide, all 5 SKILL.md files, main/eager/deferred
runtime, createServer core, tool contract types and effects, Evidence and bundle authentication, the ledger service,
evaluation and authority files, obligation tool registration, JS application service and Electron registration,
provider registry, HTTP endpoint/listener checks, Codex eval scorer and runner, readiness verifier head, install.sh,
package.json, workflows); about 150 more inspected by grep or listing; roughly 5,300 of 5,481 tracked files not read.

### Changes since the 2026-10-14 evaluation

The earlier evaluation (`docs/evaluations/2026-10-14-software-factory-architecture-evaluation.md`) examined REA at
`d9cd239` (2026-10-14, v6.5.0) in its comparison table (lines 63-74), its adoption matrix (items 6 and 13, lines
108 and 115) and its roadmap (line 235). This report was written independently and then compared with it.

| Topic | 2026-10-14 evaluation | This report (7091be2, 2026-10-22) |
|---|---|---|
| Revision and releases | `d9cd239`, v6.5.0 | 1,146 commits later (gh compare); `rea-agents-6.6.0` and `6.7.0` published 2026-10-18; main is ahead of 6.7.0 |
| Tests / CI | 1,291 test files, mutation testing, 29 workflows | Test files grew from about 1,294 to 2,081 (+787) `*.test.*` files, workflows from 29 to 33, and tracked files from 3,833 to 5,481, counted with the same glob at both commits (`d9cd239` via `gh api git/trees/d9cd239?recursive=1`, not truncated; `7091be2` via `git ls-files`). Mutation testing is confirmed nightly but non-blocking (`thresholds.break: null`). New observation: main CI was failing or cancelled on 2026-10-22 during a bulk merge |
| Tool count | "150+ tools" | 220 entries in `TOOL_EFFECTS`; 15 declare `executesForeignCode` |
| Stars | 237k in 6 months, treated as an anomaly | 365,013 stars and 91,511 forks; the same anomaly caveat applies |
| Maintainers | ~3 major + tail | Consistent: contributors morluto (2,218), N0zoM1z0 (592), kaoru0822-kitauji (562), then a long tail |
| Strongest asset | `src/domain/evidence.ts`: hashed IDs, provenance, confidence, authority, limitations, explicit unknowns | Confirmed, with a qualification: the hashed ID gives integrity and canonical form, not provenance. There is no signing key, so a well-formed record can be fabricated (§6) |
| Isolation | "This is not a sandbox" (`SECURITY.md:33`); active modes run targets with host privileges | Confirmed (§8). Also new here: the HTTP transport has no authentication (a design limit documented at `docs/mcp-contracts.md:619-622`), and non-loopback binds relax Host checks with a warning only |
| Setup | Writes `~/.claude.json` and installs a skill directly | Confirmed that setup writes client configuration and installs the bundled skill after showing a plan with backups and approval (`Setup.ts:255-290`; `SetupSkill.ts:514-541`). The registered command is version-pinned (`src/identity.ts:10-13`), but the skill's diagnostics and its approved setup-apply step use `@latest` (`SKILL.md:46,60,65,80,87-88`), and `src/identity.ts:9` defines an `@latest` `packageSpecifier` |
| Release churn | ~10 releases in 9 days | Continues: 6.0.0 to 6.7.0 between 2026-10-08 and 2026-10-18 |

Not covered in the earlier evaluation and new in this report:

- the reconstruction and parity-verification layer: the obligation ledger, the proof-authority lattice, coverage
  evaluation, `verify_reconstruction`, and partial-order process comparison (§5 path 2, §11, §12);
- the finding that no non-test code produces `rea.reconstruction-proof` Evidence;
- the untrusted-content result marker (§8);
- the Codex-based agent-experience evaluation harness, which is not run in CI (§7);
- the digest-verified deferred catalog startup (§2).

Earlier statements this report does not contradict: the MIT licence with commercial engines out of scope, the
evidence-schema pattern, the need for external isolation, and the churn risk.

### Verification corrections (2026-10-22)

- V7-1: "Changes since" Tests/CI row — growth is established with the same glob at both commits: test files about 1,294 → 2,081 (+787), workflows 29 → 33, tracked files 3,833 → 5,481.
- V7-2: §7 (and §1, §14) — 2,081 `*.test.*` files, 2,080 Vitest plus `scripts/fixtures/http3-lab.test.py`; about 16 Python test files, mostly experiment oracles (3 under `bridge/`, 10 in `experiments/analysis-efficiency/`, the rest in `tests/fixtures/` and `scripts/`), not "18 for the bridges".
- V7-3: §4, §12, §14, "Changes since" — `TOOL_EFFECTS` has exactly 220 keys (was "about 219").
- V7-4: §7 — repo-wide 59 `actions/checkout@` and 50 `actions/setup-node@` uses (16 each in `ci.yml`); all SHA-pinned (conclusion unchanged).
- V7-5: §8, §14, §15, "Changes since" — HTTP without authentication is labelled a design limit documented at `docs/mcp-contracts.md:619-622`; the [I] became [C] backed by the code reading.
- V7-6: §8, §13, "Changes since" — added `SKILL.md:65` (approved setup-apply step with `@latest`) and `src/identity.ts:9` (`packageSpecifier: …@latest`, next to the pinned `mcpCommand` at `:13`).
- V7-7: §1 — the pitch is split between `README.md:10` and `README.md:61`.
- V7-8: §13 — "Proof-authority lattice" and "Tool effects table" reclassed to "reimplement the idea".
- V7-9: §1, §14 — CI figures restated with the method: 19 success, 14 failure, 66 cancelled, 1 `action_required` of the last 100 completed main `ci.yml` runs created on or before 2026-10-22 20:00Z; the evaluated commit's `CI` run has since concluded `cancelled`.
- C-1 (corrector finding): §13 — "Untrusted-content result marker" reclassed from "directly reusable" to "reimplement the idea"; like the V7-8 rows it is a pattern to copy, not code to reuse.
