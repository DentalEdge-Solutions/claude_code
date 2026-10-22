# Jake Schincariol — Replica Skill: technical deep dive

> Repository: https://github.com/Jakeschincariol/replica-skill (repo root) · Evaluated commit: 77c9436fb3d18c3d58169efb8caf4fe906b0dc51 (2026-10-03) on main
> Other branches inspected: none (main is the only branch) · License: MIT (`LICENSE`)
> Accessed: 2026-10-22 · Method: read-only shallow clone; no code executed
> Legend: [F] verified fact · [I] inference · [C] unverified claim · [U] unknown · [F docs] fact from the official Claude Code docs at code.claude.com (cited with access date; not executed)

## 1. Summary

Replica is a pack of 11 Claude Code skills (`replica-*/SKILL.md`) plus six standard-library Python
tools. Together they walk one user through "cloning" an existing app: reverse-engineer it from public
sources, plan, design, build, wire the backend, test, measure parity, mine competitor reviews, rebrand,
write the launch material and deploy [F] (`README.md:52-66`). Its target user is an indie hacker or
small founder who wants to rebuild the core features of an existing SaaS or mobile app and sell their
own version (`plugin.json:12-20` keywords `app-clone`, `indie-hacker`, `saas`) [F]. The whole
orchestration is LLM-driven prose. No agents, hooks, orchestrator code or tool restrictions exist. The
user runs the skills in sequence and they hand off through files in a `replica/` folder [F]
(`README.md:68-75`). The deterministic part is six small CLI tools: a pure-Python PNG
decoder with a layout diff (`imgdiff.py`), a weighted feature-parity scorer (`parity.py`), a review
ranker that enforces provenance (`reviews.py`), a WCAG contrast checker (`contrast.py`), a scanner
for leftover brand identity (`sweep.py`) and a store-listing linter (`listing.py`). They are covered
by 57 unittest cases [F]. Maturity is low on maintenance: one commit, v1.0.0 in `plugin.json:4`, no
tags or releases, no CI. Twelve open community issues and PRs were unmerged 19 days after creation,
including a confirmed crash fix and a claimed plugin-loader layout fix (PR #4, whose claim current
official docs contradict; see section 16). Interest is very high: 4,540
stars and 796 forks per `gh api` on 2026-10-22 [F]. The commit carries a `Co-Authored-By: Claude Opus 5.5`
trailer, so the pack was AI-assisted [F].

**Category:** reverse-engineering/replication (primary) · skill/agent pack · spec/planning
methodology (secondary).

## 2. Architecture

**Components** [F]:

| Layer | Files | Role |
| --- | --- | --- |
| Plugin metadata | `.claude-plugin/plugin.json`, `.claude-plugin/marketplace.json` | Claude Code plugin + single-plugin marketplace; `"skills": "./"` (`plugin.json:21`) |
| Skills (11) | `replica-{recon,architect,design,build,backend,test,diff,entrepreneur,brand,launch,deploy}/SKILL.md` | Prose workflows with YAML frontmatter (`name`, `description` only) |
| Templates | `replica-recon/recon-map.md`, `replica-recon/features.csv`, `replica-architect/architecture.md`, `replica-design/tokens.json`, `replica-test/{test-plan.md,bug-report.md,e2e.example.spec.ts}`, `replica-deploy/preflight.md`, `replica-launch/listing.example.json`, `replica-entrepreneur/themes.json` | Artifact schemas the skills fill in |
| Tools (6) | `replica-diff/imgdiff.py` (456 lines), `replica-diff/parity.py` (228), `replica-entrepreneur/reviews.py` (311), `replica-brand/sweep.py` (177), `replica-launch/listing.py` (181), `replica-design/contrast.py` (152) | Deterministic stdlib-only CLIs with exit-code contracts |
| Tests | `tests/*.py` (57 test functions, `unittest`) | Tool unit tests + repo-shape tests |

**Tech stack** [F]: Markdown skills; Python 3 stdlib only. The imports are `argparse, csv, json, re, struct,
zlib, math, os, sys, datetime, unicodedata` and none is a network module (grep for
`urllib|http|socket|subprocess|requests|os.system|eval(|exec(` across `*.py` returned nothing).
README states Python ≥ 3.8 (`README.md:50`) [C, not executed]. No package manifest and no pinned
dependencies.

**External services and models** [F]: the pack itself calls none. The skills tell the agent to
recommend services for the *clone*: Next.js, Supabase/Neon, Drizzle/Prisma, Stripe, Resend/Postmark,
Vercel, Expo (`replica-architect/SKILL.md:26-38`). They also point at Playwright and axe
(`replica-test/SKILL.md:47-53`) and at public review feeds such as the Apple RSS feed and the HN
Algolia API (`replica-entrepreneur/SKILL.md:35-38`). No model is named and no frontmatter `model:`
or `allowed-tools:` is set in any skill (grep returned nothing).

```mermaid
flowchart LR
  U[User + Claude session] -->|/replica-recon URL| R[recon]
  R -->|recon.md, features.csv, screens/| A[architect]
  A -->|architecture.md, schema.sql| D[design]
  D -->|design/tokens.json, components.md| B[build]
  B -->|clone-screens/, build-log.md, features.csv clone col| BE[backend]
  BE -->|backend.md, .env.example| T[test]
  T -->|test-plan.md, bugs.md, e2e/| DF[diff]
  DF -->|parity.md, diffs/*.json| E[entrepreneur]
  E -->|reviews.csv, feedback.md, fixes.md, +features rows original=no| BR[brand]
  BR -->|brand.md, brand.json, tokens| L[launch]
  L -->|launch/*.md, listing.json| DP[deploy]
  DP -->|deploy.md + user 'go'| LIVE[(live app)]
  DF -. parity.py / imgdiff.py .-> DF
  E -. reviews.py .-> E
  BR -. sweep.py .-> BR
  D -. contrast.py .-> D
  L -. listing.py .-> L
  DP -. parity.py, sweep.py, listing.py, playwright .-> DP
```

## 3. Agents

There are no agent definitions: no `.claude/agents/`, no subagent dispatch and no role files [F]
(`git ls-files` lists 39 files and none is an agent). Every step runs in the main Claude session that
invokes the skill. Separation of concerns comes only from the order of skills and the files they
exchange (section 6). The "clean-room" framing therefore has **no role separation**: the same session
that reads the original's screenshots and help pages also writes the code [I]. A traditional
clean-room process keeps specification writers separate from implementers. Here that separation is
approximated by the `recon.md` specification artifact but never enforced
(`replica-build/SKILL.md:14,47-49` reads both `recon.md` and the reference screenshots).

## 4. Skills, commands and prompts

All 11 skills follow one shape [F]: frontmatter `name` + a long trigger-phrase `description`
(459–639 chars), an `Reads … Writes …` I/O contract, a **"The rules"** block that comes before the
workflow, numbered steps, and an `Output` section that names the next skill. Body sizes run from
530 words (`replica-test`) to 929 words (`replica-recon`), about 7,500 words in total [F] (`wc -w`).

| Skill | Triggers (from description) | What it does | Notable structure |
| --- | --- | --- | --- |
| `replica-recon` | "clone this app", "reverse engineer X", "how does X work", "copy this app", pasted app/store URL (`:7-10`) | Builds a source table, then a screen inventory (S01…), flows (F01…), components, an inferred data model with evidence + confidence, the feature matrix, a "cannot be cloned" list and a size estimate (`:47-128`) | Rules first (`:26-45`); 8-row source priority table (`:58-69`); stable IDs "every other file refers to" (`:73`); states checklist (`:77-78`); `skip` rows with reason (`:119-122`); T-shirt sizing S/M/L/XL (`:124-128`) |
| `replica-architect` | "plan the clone", "what stack", "write the schema" (`:8-10`) | Stack table with defaults, SQL schema rules, API table per flow, "parts that bite", build order (`:21-109`) | Hard prerequisite: "If there is no recon map, stop" (`:18-19`), the only explicit prerequisite check in the pack; "only official, public APIs … never the original app's private endpoints" (`:92-93`) |
| `replica-design` | "match the design", "make it look like X", "design tokens" (`:8-10`) | Measures colour roles, type scale, spacing etc. from screenshots into `tokens.json`; component specs; primitives page; contrast gate (`:39-99`) | Explicit "never take" list: logos, icons, licensed fonts, copy, brand colour; names trade dress (`:29-37`) |
| `replica-build` | "build the clone", "build screen S07" (`:7-9`) | Shell → vertical slice → screen by screen with every state; updates `features.csv`; screenshots each screen for diff; one commit per screen (`:29-59`) | Clean-room rules (`:20-27`); per-screen Definition of Done checklist (`:61-69`); "do not quietly ship half of it" (`:73-75`) |
| `replica-backend` | "add login", "connect Stripe", "add Google Calendar" (`:7-9`) | Auth, migrations + RLS, Stripe Checkout/webhooks, email/jobs, integrations, security checklist (`:28-84`) | "Claude never signs up for services, never types a password, card or live key" (`:22-25`); test mode first (`:26`) |
| `replica-test` | "test my clone", "find bugs", "QA this" (`:7-10`) | Test plan per flow (happy / edge / negative with IDs F01-H1, F01-E3, F01-N2), Playwright specs, manual click-through, bug reports S1–S4, TDD fix loop (`:25-81`) | Rule: "Test your clone, not the original. Never load test, fuzz, script or hammer the original app's servers" (`:21-23`); "Only report what you reproduced" (`:74-75`) |
| `replica-diff` | "how close is my clone", "parity check", "is it ready" (`:8-10`) | Runs `parity.py` + `imgdiff.py`; a manual behaviour diff; writes the `parity.md` verdict (`:34-87`) | "Parity means it does the same job, not that it looks the same" (`:26`); verdict rubric not shippable / shippable / better than the original (`:81-85`) |
| `replica-entrepreneur` | "what do people hate about X", "read the reviews", "find the gap" (`:9-11`) | Collects 100+ reviews from 3+ sources into CSV, ranks them with `reviews.py`, writes hate/missing/unsolved lists, a fix plan and positioning (`:44-106`) | Non-negotiable rules: never fabricate, verbatim + linked, reading not scraping, no fake reviews (FTC 2024 rule cited), reviewers are not testimonials (`:25-42`) |
| `replica-brand` | "name my app", "rebrand the clone", "check for leftovers" (`:8-10`) | Name generation + screening checks (USPTO, EUIPO, CIPO, WIPO, domain, stores, handles), new palette, logo brief, voice, sweep (`:28-104`) | "Mark each **to run**, or the result with the date it was run. Never write 'available' for a check nobody ran" (`:42-43`) |
| `replica-launch` | "landing page", "pricing", "App Store listing" (`:8-10`) | Landing page sections, pricing research with URL + date, store listing lint, launch plan (`:34-95`) | "No fake proof" rules (`:27-32`); cites Apple Guideline 4.1 Copycats (`:80-83`) [C] |
| `replica-deploy` | "deploy it", "ship it", "connect my domain" (`:9-10`) | Preflight (playwright, parity, sweep, listing, build), production services, DNS + email DNS, monitoring, mobile builds (`:27-98`) | "Nothing goes live without the user's go" (`:20-21`); "The user buys and signs in" (`:22-24`); "Not until it is rebranded … No exceptions" (`:25`) |

**Trigger breadth** [I]: `replica-recon`'s description includes generic phrases such as "how does X
work" and "map out X" (`replica-recon/SKILL.md:8`). These can fire a cloning workflow on ordinary
product questions. No negative triggers ("Not for: …") exist in any description.

**Prompt-injection content:** none found that addresses an evaluator or tries to subvert an agent
[F]. The skill bodies are imperative instructions to Claude, which is normal for skills. The README
tells users to paste the repo URL plus "install skill" into Claude (`README.md:21-27`). That is an
install instruction aimed at an AI, not an injection, but it installs from unpinned `main`.

## 5. Orchestration and execution workflows

**Execution model** [F]: fully LLM-driven, human-sequenced. No code chains the skills. Each
`Output` section names the next slash command (for example `replica-recon/SKILL.md:132-134`,
`replica-diff/SKILL.md:91-93`), and the user invokes it. `replica-diff` branches back to build or
forward to entrepreneur depending on the gaps (`:91-93`); `replica-build` branches to backend or test
(`:86-87`). Deterministic computation is pushed into the six CLIs, which communicate via **exit codes**:
0 = pass, 1 = gate failure, 2 = input error (`parity.py:215-224`, `sweep.py:167-173`,
`listing.py:177`, `contrast.py:139-148`, `imgdiff.py:434-452`).

**Concurrency** [F]: none. Purely sequential, single session, no subagents and no parallel dispatch.

**Retries and recovery** [F]: no mechanical retries. Recovery is prose loops: the TDD bug-fix loop
(`replica-test/SKILL.md:77-81`), "fix until it says clean" for the sweep
(`replica-brand/SKILL.md:103`), and diff → build for gaps (`replica-diff/SKILL.md:91-92`).

**Human approval gates** [F]:
- Scope confirmation: "Ask three things, or propose answers and get a yes" (`replica-recon/SKILL.md:49`).
- Account and secret creation is reserved to the user (`replica-backend/SKILL.md:22-25`,
  `replica-deploy/SKILL.md:22-24`).
- Deploy go/no-go: "Nothing goes live without the user's go. Show the preflight results and ask"
  (`replica-deploy/SKILL.md:20-21`); `preflight.md:3` records "Go from user".
- Manual checks the agent cannot automate: "give the user the checklist and wait for answers"
  (`replica-test/SKILL.md:58-60`).

**Gate strength** [F/I]: the deploy preflight says "Any failure stops the deploy"
(`replica-deploy/SKILL.md:48`). Only some checks fail mechanically, though:
- `sweep.py` exits 1 on any hit (`sweep.py:173`): a mechanical gate.
- `listing.py` exits 1 on any error-level issue (`listing.py:177`): a mechanical gate.
- `parity.py` as invoked in the preflight (`replica-deploy/SKILL.md:33`: no `--fail-under`) **always
  exits 0** whatever the must-have status (`parity.py:218-224`). Missing must-haves only print the
  text "Not shippable yet" (`parity.py:165-168`), so the "must-haves done" gate depends on the LLM
  reading that text [F].
- Open S1/S2 bugs, legal pages and account deletion are checked "by hand" (`replica-deploy/SKILL.md:43-46`) [F].
- `contrast.py` is not in the deploy preflight, although `replica-design` requires zero AA failures
  (`replica-design/SKILL.md:97-98`) [F].
- None of these gates is wired into a hook, so the agent decides to run them [F].

**Path ambiguity in the preflight** [I]: `python3 ../replica-diff/parity.py replica/features.csv`
(`replica-deploy/SKILL.md:33`) mixes a path relative to the skill folder (`../replica-diff/`) with
one relative to the project (`replica/features.csv`); the note at `:39-41` leaves the LLM to resolve
them. No plugin-root variable is used.

### Traced path A: specification → build → parity score

1. **Entry:** user runs `/replica-recon <url>`. `replica-recon/SKILL.md` Step 7 (`:111-115`) writes
   `replica/features.csv` from the template `replica-recon/features.csv` (header
   `feature,area,priority,original,clone,notes`, `features.csv:1`), with `clone=no` on every row and
   `skip` rows for what cannot be cloned (`:119-122`; template row `features.csv:19`).
2. **Mutation:** `/replica-build` Step 3.6 sets rows to `yes` or `partial` (`replica-build/SKILL.md:56`)
   and saves screenshots to `replica/clone-screens/S07.png` (`:57-58`). `/replica-backend` updates
   rows (`replica-backend/SKILL.md:89-90`). `/replica-entrepreneur` appends rows with `original=no`
   (`replica-entrepreneur/SKILL.md:89-91`).
3. **Visual input:** `/replica-diff` Step 2 runs `imgdiff.py <orig> <clone> --json`
   (`replica-diff/SKILL.md:20,57`). `imgdiff.main` (`imgdiff.py:416`) → `read_png` (`:107`: chunk
   walk, `zlib.decompress` `:152`, `_unfilter` `:56`, `_samples` `:88`, alpha over white `:184`) →
   `compare` (`:275`). `compare` scales both images to `min(480, wa, wb)` (`:280-282`), converts to
   grey (`:230`), builds `edges` (`:234`) and cuts a 12-column grid of square cells (`:334-336`). Per
   cell it computes `sim = 1 - |da-db|/max(da,db)` on edge density and skips cells empty in both
   (`:345-351`). The score is the mean of `sims` (`:358`), cells with sim < 0.6 are flagged and
   grouped into 4-connected regions mapped back to the original's pixels (`_regions` `:249`, `:360-370`),
   then `verdict` (`:385`) and JSON output (`:444-445`).
4. **Scoring:** `parity.py replica/features.csv --visual replica/diffs/*.json --markdown`
   (`replica-diff/SKILL.md:21`). `parity.main` (`:204`) → `load` (`:45`: column check, lower-cased keys)
   → `score` (`:66`). `score` excludes `original=no` rows as extras (`:75-77`) and `skip` rows
   (`:78-80`), weights must 3 / should 2 / could 1 and credits yes 1 / partial 0.5 / no 0
   (`:36-37,87-89`), then computes the feature score, per-area scores weakest first (`:95-105`) and
   the missing list in build order (`:107-108`). `visual_scores` (`:130`) → `combine` (`:143`)
   gives overall = 0.8 × features + 0.2 × layout (`:148`). `render` (`:154`) prints "Not shippable
   yet" when must-haves are incomplete (`:165-168`).
5. **Output/state:** `replica/parity.md`. The LLM applies the verdict rubric
   (`replica-diff/SKILL.md:81-85`), which `parity.py` does not compute [F].

### Traced path B: rebrand sweep → deploy gate

1. `/replica-brand` writes `replica/brand.json` with `avoid`, `domains`, `colors`
   (`replica-brand/SKILL.md:25-26`) and adds the original's brand colours (`:69-70`).
2. `sweep.py . --config replica/brand.json` (`:97`). `sweep.main` (`sweep.py:144`) merges CLI and
   config lists (`:154-166`) and refuses an empty search with exit 2 (`:167-170`) → `sweep`
   (`:77`). `build_patterns` (`:51`) turns "Acuity Scheduling" into `Acuity[\s_-]?Scheduling`,
   case-insensitive, with no word boundaries, so it matches inside identifiers (`:57-59`). Domains
   become escaped literals (`:60-63`). `os.walk` prunes `SKIP_DIRS` and the root-level `replica/`
   folder (`:82-91`), checks folder and file names (`:92-106`), skips lock files, files over 2 MB and
   binary files (`:99,108`), then scans each line for names, domains and normalised hex colours
   (`:114-124`, `norm_hex` `:44`).
3. `render` (`:128`) prints the hits, and the exit is 1 if any (`:173`).
4. `/replica-deploy` Step 1 re-runs the sweep as a preflight item (`replica-deploy/SKILL.md:34`),
   records it in `deploy.md` (`preflight.md:10`), and the LLM must refuse to proceed
   (`replica-deploy/SKILL.md:25,48`) and then ask the user for "go" (`:20-21`).

### Traced path C: review evidence → fix plan → feature matrix

1. `/replica-entrepreneur` gathers rows `source,url,date,rating,text` by reading pages or official
   feeds (`replica-entrepreneur/SKILL.md:44-60`).
2. `reviews.py replica/reviews.csv --out replica/feedback.md` (`:65`). `main` (`reviews.py:273`) →
   `load_themes` (`:50`, regex lists from `themes.json`) → `load_reviews` (`:87`). It drops rows
   without a URL matching `^https?://` or without text (`:104-106`) and de-duplicates on normalised
   text (`:107-111`). `analyse` (`:153`) weights each review by rating (1★=1.0 … 5★=0.2, unrated 0.6)
   and halves the weight after 18 months (`weight` `:128-135`). It matches every theme (multi-label,
   `:163-170`), takes the first matching sentence verbatim as the quote (`snippet` `:138-150`),
   collects requests (`:171-174`) and keeps unthemed ≤2★ reviews (`:175-176`). A theme is `thin` if
   it has fewer than 3 reviews or one source (`:196`). `render` (`:218`) warns below 30 reviews
   (`:228-231`).
3. The LLM writes `fixes.md`, adds fix rows with `original=no` to `features.csv` (`:89-91`), and
   `parity.py` lists them as "Yours, not in the original (not scored)" (`parity.py:186-190`).

## 6. Context and state management

**State is entirely file-based in the user's project under `replica/`** [F]. From the Reads/Writes
lines in each SKILL.md:

| Artifact | Producer | Consumers |
| --- | --- | --- |
| `recon.md` | recon | architect, design, build, test |
| `features.csv` (central ledger) | recon (create), build/backend (clone col), entrepreneur (extra rows) | architect, diff (`parity.py`), deploy |
| `screens/` (original screenshots) | recon | design, build, diff |
| `architecture.md`, `schema.sql` | architect | build, backend |
| `design/tokens.json`, `tokens.css`, `components.md` | design; brand rewrites values | build, brand, launch |
| `clone-screens/`, `build-log.md` | build | diff |
| `backend.md`, `.env.example` | backend | deploy |
| `test-plan.md`, `bugs.md`, `e2e/` | test | deploy (by hand) |
| `diffs/*.json`, `parity.md` | diff | entrepreneur, deploy |
| `reviews.csv`, `feedback.md`, `fixes.md` | entrepreneur | brand, launch, architect build-order step 4 |
| `brand.md`, `brand.json` | brand | launch, deploy, `sweep.py`, `listing.py` (via `avoid`) |
| `launch/{landing,pricing,launch-plan}.md`, `listing.json` | launch | deploy |
| `deploy.md` | deploy | — |

**Cross-referencing via stable IDs** [F]: screens `S01…` ("IDs are stable … Every other file refers
to them", `replica-recon/SKILL.md:73`), flows `F01…`, test cases `F01-H1/E3/N2`
(`replica-test/SKILL.md:39`), bugs `BUG-001` (`bug-report.md:1`), and commits named per screen
(`replica-build/SKILL.md:59`). This gives traceability from specification to screen to test to bug.

**Context building and compression** [F]: none beyond the artifacts themselves. Each skill reads
the upstream files; no summarisation step, context pack or token budget exists.

**Resumability** [I]: implicit. Because state lives in files, any skill can be re-run in a new
session, and the README says any skill can run alone (`README.md:116-117`). There is no state machine,
lock or checkpoint. Only `replica-architect` checks that its prerequisite exists
(`SKILL.md:18-19`). The other skills assume their inputs exist.

**Persistence caveat** [I]: no skill tells the user to gitignore `replica/screens/` (the original's
screenshots) or `replica/reviews.csv` (third-party review text). `sweep.py` deliberately skips
`replica/` (`sweep.py:88`). In a public repo these research artifacts would be published along with
the clone. The only `.gitignore` guidance concerns `.env*` (`replica-backend/SKILL.md:76`).

## 7. Engineering practices and testing

**Tests** [F]: 57 `unittest` test functions across 6 files (`grep -c 'def test_'`): `test_imgdiff.py`
14, `test_contrast_listing.py` 12, `test_reviews.py` 11, `test_parity.py` 10, `test_repo.py` 5,
`test_sweep.py` 5. `tests/_load.py` imports scripts from the hyphenated folders via `importlib`
(`_load.py:9-14`). Run command: `python3 -m unittest discover -s tests -v` (`README.md:153`). **Not
executed** here. A third-party PR (#3) claims all 57 pass on Python 3.8–3.14 [C].

Coverage highlights [F]:
- `imgdiff`: RGB round-trip, all 5 PNG filter types for RGBA, alpha over white, grey, 2-bit palette
  and 16-bit, interlace refusal, non-PNG refusal (`test_imgdiff.py:91-134`). Layout properties: an
  identical image scores 100, a rebrand keeps the layout score ≥ 90 while the pixel score drops, a
  moved button is located in the lower-left, a blank clone scores "different", retina scaling, height
  delta (`:138-182`). CLI JSON and `--fail-under` (`:186-206`). The tests use a self-written PNG
  encoder, so the decoder is checked against independent encoding logic (`:36-77`).
- `parity`: weighted maths, skip/extras exclusion, build-order sort, weakest area, "not shippable"
  text, 20% visual fold-in, bad values non-fatal, missing column exit 2, `--fail-under`, shipped
  template parses (`test_parity.py:39-102`).
- `reviews`: unsourced rows dropped, duplicates removed, top theme, **every quote is a substring of
  its source row** (`test_reviews.py:69-76`), requests extracted, thin flag, unthemed negatives,
  ageing, small-sample warning.
- `sweep`: names, paths, domains, colours, identifier embedding (`AcuitySchedulingSync`), skip rules,
  short-hex equivalence, exit codes (`test_sweep.py:44-81`).
- `contrast`/`listing`: known WCAG ratios (#767676 passes, #777777 fails), nested token flattening,
  default pairs, shipped templates pass, length limits, avoid-name error, claims/keyword waste,
  grapheme counting (`test_contrast_listing.py:15-114`).
- Repo shape: exactly the 11 skill folders, frontmatter names, description length > 200 chars,
  plugin manifest values, README copy, and **no em-dashes anywhere** (`test_repo.py:23-75`). The
  repo tests hard-code the skill list and the README "reel copy" (`test_repo.py:8-12,47-63`), which
  makes them brittle to edits [I].

**CI** [F]: none (no `.github/`). PR #3 proposing a CI matrix is open and unmerged.

**Linting and typing** [F]: none (no config files, no type hints).

**Eval suites for the skills** [F]: none. No trigger tests, scenario evals or golden transcripts.
`test_repo.py` checks only the frontmatter's shape, not whether the skills behave correctly.

**Verification applied to the software the pack produces** [F]: the most developed part of the pack.
- Per-screen Definition of Done (`replica-build/SKILL.md:61-69`).
- Playwright specs per flow that fail on console errors and on any 5xx, with an axe scan per screen
  (`replica-test/SKILL.md:43-53`, `e2e.example.spec.ts:7-14,25-26`), and role/label selectors that
  survive the rebrand (`e2e.example.spec.ts:2`).
- Write the failing test first, then fix (`replica-test/SKILL.md:79-81`).
- "Only report what you reproduced" (`:74-75`).
- The parity and layout scores, WCAG contrast, the leftover-identity sweep, the listing lint, and an
  RLS test that a second user gets nothing back (`replica-backend/SKILL.md:42-43`).

**Independence**: none. The same session builds, tests and marks `features.csv`, so the parity number
rests on the builder's own `clone` column entries (`replica-build/SKILL.md:56`). No test results
are mapped to feature rows [I].

**Known defects** [F]:
- `imgdiff.read_png` unpacks IHDR without a length check (`imgdiff.py:127`), and `main` catches only
  `PngError, OSError, zlib.error` (`:434`). A truncated IHDR therefore raises an uncaught
  `struct.error`. This matches open issue #10; fix PR #12 is unmerged.
- `reviews.py` URL check `re.match(r"^https?://", url)` is case-sensitive (`reviews.py:104`), so
  `HTTPS://…` rows are dropped. Open PR #7 describes the same issue.
- `sweep.py` docstring suggests `--include-replica` "if it sits inside public/" (`sweep.py:22-23`),
  but only a **root-level** `replica/` is skipped anyway (`:88`). That advice is redundant and could
  mislead [F].

## 8. Security, isolation and observability

**Permission model** [F]: the skills declare no `allowed-tools` and no hooks, so they inherit the
session's permissions. There is no `--dangerously-skip-permissions` usage, no settings file and no
sandbox, container or worktree. Behavioural limits are prose only:
- never sign up, type passwords or cards, or paste live keys (`replica-backend/SKILL.md:22-25`,
  `replica-deploy/SKILL.md:22-24`);
- deploy needs the user's "go" (`replica-deploy/SKILL.md:20`).

**Commands the skills ask the agent to run** [F]:
- `npm i -D @playwright/test && npx playwright install chromium` (unpinned; `replica-test/SKILL.md:47-49`);
- `npm audit` (`replica-backend/SKILL.md:83`);
- `npm run build`, `npx playwright test` (`replica-deploy/SKILL.md:32,36`);
- `eas build` / `eas submit` (`:95`);
- `whois` (`replica-brand/SKILL.md:51`).

These are ordinary developer commands on the user's own project. Installing the pack itself, by
"paste the URL + install skill" (`README.md:21-27`) or `git clone` + `cp` (`:40-43`), pulls unpinned
`main` [F].

**Tool safety** [F/I]:
- The six tools are stdlib-only and import no network or subprocess modules [F]. They read local
  files and write only to user-given paths (`imgdiff --out`, `reviews --out`).
- `imgdiff.py:152` calls `zlib.decompress` with no size cap, and decoding is per-pixel Python lists.
  A hostile or huge PNG could exhaust memory (a decompression bomb) [I]. The risk is low because the
  inputs are the user's own screenshots.
- `sweep.py` walks with `os.walk` defaults (no symlink following) and caps files at 2 MB
  (`sweep.py:77,108`) [F].
- `listing.py:50,53` contains **literal invisible characters** in string literals: U+200D ZERO
  WIDTH JOINER, and the variation selectors U+FE0F/U+FE0E (confirmed with `od -c`). They are
  functionally correct for grapheme counting. They are not an injection vector, but they are
  invisible in review [F].

**Secrets** [F]: no secret-shaped values in the repository. The grep for key, token and password
patterns returned only prose and `tokens.json` design tokens. The skills prescribe `.env.example` with
names only (`replica-backend/SKILL.md:25`) and secrets only in env vars (`:76`).

**Prompt-injection exposure** [I]: high in principle, with no mitigation.
- `replica-recon` reads untrusted third-party web content: help centres, marketing sites, store
  listings, walkthrough pages (`SKILL.md:58-69`).
- `replica-entrepreneur` copies verbatim review text from App Store, G2, Reddit and HN into
  `reviews.csv` and then into `feedback.md`, which the LLM reads back (`SKILL.md:44-60,65`).
- No skill tells the agent to treat fetched pages or review text as data rather than instructions.
- Review text is the most attacker-controllable input in the pipeline: anyone can post a review or
  a Reddit comment. It flows into planning (`fixes.md`) and from there into the build.

**Legal, ToS and safety boundaries.** This is the most distinctive security-adjacent content in the
pack. What the skills say [F]:

| Boundary | Where | Mechanism |
| --- | --- | --- |
| Public sources + user's own account only; never another's account, never ask for a password, never bypass a paywall or login | `replica-recon/SKILL.md:32-34`, `README.md:163-167` | Prose |
| No crawlers, bulk downloads or loops; read at human speed with the user present | `replica-recon/SKILL.md:35-37` | Prose |
| No JS bundles, decompiling or network-call logging; public API docs OK | `replica-recon/SKILL.md:38-40` | Prose |
| Check whether the user's account ToS forbids building a competitor; if so, public sources only | `replica-recon/SKILL.md:41-43` | Prose; no artifact records that the check was done |
| Screenshots are reference only, never shipped | `replica-recon/SKILL.md:44-45` | Prose; `sweep.py` skips binaries and `replica/`, so a shipped screenshot is **not** detected |
| Clean room: never paste HTML/CSS/JS/SVG/images, never load from the original's domain or CDN | `replica-build/SKILL.md:20-23` | Prose; `sweep.py` catches the original's **domain** in code (`sweep.py:60-63`) |
| Fresh copy: "Matching what a button does is parity. Matching its sentence is copying." | `replica-build/SKILL.md:24-25` | Prose; no copy-similarity check exists |
| No logos, icons, illustrations, licensed fonts or brand colour; open icon sets and fonts; trade dress named | `replica-design/SKILL.md:29-37` | Prose + `sweep.py --colors` |
| Do not chase pixel parity; the exact look is trade dress | `replica-diff/SKILL.md:30-32`, `imgdiff.py:19-21` | Prose; layout mode ignores colour by design |
| Never load-test, fuzz or script the original's servers | `replica-test/SKILL.md:21-23` | Prose |
| Official APIs only, own keys, never the original's private endpoints or OAuth client | `replica-architect/SKILL.md:92-93`, `replica-backend/SKILL.md:19-21` | Prose |
| Out-of-scope list: licensed content, the network, owned data, partner deals, hardware, regulated licences | `replica-recon/SKILL.md:117-122` | `skip` rows excluded from parity (`parity.py:78-80`) |
| Never fabricate reviews or numbers; verbatim + linked; FTC 2024 fake-review rule cited | `replica-entrepreneur/SKILL.md:27-40` | `reviews.py` drops unlinked rows and quotes only substrings (`reviews.py:104-106,138-150`) |
| Reviewer quotes are research, not testimonials | `replica-entrepreneur/SKILL.md:41-42`, `replica-launch/SKILL.md:30` | Prose |
| Reading, not scraping review sites; official feeds within their terms | `replica-entrepreneur/SKILL.md:32-38` | Prose |
| Name not confusingly similar; trademark screening across 4 registries with "to run" vs dated result | `replica-brand/SKILL.md:34-57` | Prose; "screening checks, not legal clearance" |
| Original's name kept out of name, listing, keywords and ads | `replica-launch/SKILL.md:31-32`, `replica-entrepreneur/SKILL.md:104-106` | `listing.py` error on `avoid` names (`listing.py:94-99`) |
| Must rebrand before launch | `replica-deploy/SKILL.md:25`, `README.md:169-170` | `sweep.py` exit 1 (`sweep.py:173`), run by the LLM |
| Not legal advice; consult a lawyer | `README.md:184-186`, `replica-brand/SKILL.md:56-57`, `replica-entrepreneur/SKILL.md:106` | Disclaimer |

**What the pack lacks** [F, from greps over all SKILL.md and README]:
- **No mention of patents.** A clean-room rebuild avoids copying code but not patented functionality.
- **No mention of copyright** as such.
- No anti-circumvention or computer-access statute named (DMCA, CFAA and equivalents), though
  "never get past a paywall or a login by any trick" covers the behaviour.
- No robots.txt.
- **No terms-of-service check for public websites.** The ToS check covers only "the user's account"
  (`replica-recon/SKILL.md:41-43`). The README promises "never scrapes … against a site's terms"
  (`README.md:164-165`), but recon has no step to read the public site's terms.
- No EU database-right or data-ownership caveat beyond "data the app owns" (`:120`).
- No retention or privacy guidance for third-party review text and original screenshots kept in
  the repo.
- No refusal criteria. Nothing tells the agent to decline a clone because of the target type, for
  example a regulated health or banking app. Those appear only as out-of-scope **features**
  (`:121`), not as stop conditions.

Inference [I]: the README says "the skills enforce it" (`README.md:17`). Most of these boundaries
are LLM-honoured instructions; the hard checks are limited to `sweep.py` (names, domains, hex
colours in text files), `listing.py` (names in store metadata) and `reviews.py` (provenance).
Nothing checks whether copy, images, SVG paths or logos were copied.

**Observability** [F]: no logging, tracing, metrics or cost reporting for the pack itself. The
project-level audit trail is the artifacts: `build-log.md` (`replica-build/SKILL.md:71-75`),
`bugs.md` with the fix commit (`replica-test/SKILL.md:81`), `deploy.md` with check results
(`replica-deploy/SKILL.md:31`), and dated trademark-check rows (`replica-brand/SKILL.md:42-43`).
For the deployed clone the pack recommends Sentry, uptime checks and analytics
(`replica-deploy/SKILL.md:86-91`).

## 9. Efficiency

- **Always-loaded footprint** [F/I]: 11 descriptions totalling about 5,700 characters
  (`awk` over frontmatter), roughly 1.4k tokens [I] of permanent skill-listing context.
- **On-demand footprint** [F]: SKILL.md bodies of 530–929 words each, with no `references/`
  progressive disclosure; templates are separate files that are read only when needed.
- **Offloading to deterministic tools** [F]: scoring, ranking, sweeping, linting and contrast maths
  run in Python. The LLM only reads compact text or JSON reports instead of reasoning over raw CSV,
  pixel data or the codebase. This is the main token economy in the design.
- **Model routing and caching** [F]: none; no model is specified anywhere.
- **Tool runtime** [I, not executed]: `imgdiff.py` decodes every pixel into Python tuples
  (`imgdiff.py:157-180`) *before* downscaling to 480 px (`:280-282`). A 2880×1800 retina screenshot is
  about 5.2 M tuples, likely seconds of CPU and hundreds of MB of RAM per image. The stdlib-only
  choice trades speed for zero-install portability.
- **Operational overhead** [F]: zero setup. No pip install, no API key, no MCP server
  (`README.md:3-4,50`). The cost of running the pipeline is the user's Claude session and the
  hosting/SaaS services chosen for the clone.

## 10. Continuous improvement

Not present for the pack itself [F]: no eval-driven refinement, no telemetry and no lesson capture
across projects. Within a single project there are feedback loops on the **product**:
- the diff → build gap loop (`replica-diff/SKILL.md:91-92`);
- the TDD bug-fix loop (`replica-test/SKILL.md:77-81`);
- the review-mined fix plan that adds rows to the ledger (`replica-entrepreneur/SKILL.md:87-91`);
- `build-log.md` recording "what was harder than expected" (`replica-build/SKILL.md:73-75`);
- user-editable `themes.json` for each category (`themes.json:2`).

## 11. Reference-driven development and reverse engineering

This is the core of the repository. Each sub-capability is assessed below.

### 11.1 Using an existing app as the reference

- **Source hierarchy** [F]: an 8-row table ranked "in order of value" (`replica-recon/SKILL.md:58-69`):
  help centre (most complete feature list and settings), pricing page (which features they gate),
  changelog, app store listing (screens), walkthrough videos, marketing site, the user's own account,
  and public API docs ("the data model, almost for free").
- **Requirement:** "a URL on every row" (`:58`), and `recon-map.md:7-11` has a sources table with
  URL and notes columns. Provenance is therefore a first-class part of the specification.
- **Scoping before extraction** [F]: platform, the slice ("'All of Notion' is not a project … Default
  to the core loop: the one flow users pay for"), and the audience (`replica-recon/SKILL.md:49-55`).

### 11.2 Specification extraction

A structured, ID-keyed specification model [F]:
- **Screen inventory**: `ID | screen | route | purpose | key components | states seen`, with states
  enumerated (empty, loading, filled, error, permission denied, mobile), because "An empty state you
  did not record is an empty state you will not build" (`replica-recon/SKILL.md:71-78`).
- **Flows**: goal plus a screen path plus edge cases. "Count the clicks on the happy path. It
  becomes the number to beat" (`:80-90`; template `recon-map.md:23-30`).
- **Components**: name, variants, states, the screens that use it. This feeds the design skill
  (`:92-96`).
- **Inferred data model**: entities and fields **with evidence (screen IDs, help articles) and a
  confidence of high / medium / guess**. "Mark guesses as guesses" (`:98-109`; `recon-map.md:38-46`).
  `replica-architect` turns it into SQL with explicit rules: UUID PKs, owner columns, explicit
  `on delete`, indexes, check constraints, `timestamptz`, integer cents, RLS or a per-query auth
  check. Invariants such as double-booking become DB constraints, not UI checks
  (`replica-architect/SKILL.md:44-81`).
- **Feature matrix** as a CSV contract: `feature, area, priority (must/should/could), original
  (yes/no), clone (yes/partial/no/skip), notes` (`replica-recon/SKILL.md:111-115`;
  `features.csv:1`). It is the single ledger tying specification, build progress, parity scoring
  and differentiation together.
- **Explicit non-goals**: `skip` rows with reasons (licensed content, network, owned data, partner
  deals, hardware, regulated licences) are excluded from the score instead of counting as failures
  (`replica-recon/SKILL.md:117-122`; `parity.py:78-80`).
- **Honest sizing**: S/M/L/XL, where XL means "rescope it", based on the counts and named hard parts
  (`:124-128`).

### 11.3 UI/UX reconstruction

- **Design-system extraction as roles, not values** [F]: colour roles (bg, surface, border,
  border-input, text, text-muted, accent, on-accent, danger, success, warning), noting "count how many
  greys … Usually 5 to 7". A type scale snapped to steps, a spacing base of 4 or 8, radius, shadow,
  motion and layout metrics, measured with a colour picker rather than guessed
  (`replica-design/SKILL.md:39-51`).
- **Rebrand separation** [F]: the token **names** stay and the values change, so the rebrand
  only swaps values (`replica-design/SKILL.md:55`; `tokens.json:2`). Components must use tokens and
  never raw hex (`replica-build/SKILL.md:26-27`).
- **Component specs** list variants, sizes, states (including focus-visible, disabled, loading),
  tokens, a11y and the screens that use them (`replica-design/SKILL.md:70-86`). Primitives are built
  in isolation on a `/design` route or Storybook and screenshotted before any screen
  (`:88-93`).
- **Screen reconstruction**: shell → vertical slice of the core loop on a fake data layer with the
  same signatures → screen by screen, every state, at 390 px and 1440 px
  (`replica-build/SKILL.md:29-69`). Screenshots are used "for layout and hierarchy. Not for pixels"
  (`:49`).
- **Asset hygiene**: open icon sets (Lucide, Phosphor, Heroicons, Tabler), open fonts with the same
  job, fresh copy, a placeholder accent until the brand step (`replica-design/SKILL.md:29-37`).

### 11.4 Visual verification

- **Capture protocol** [F]: the same viewport (1440×900, 390×844) and the same state (data shape,
  tab, login) for both screenshots; originals in `replica/screens/`, clone shots in
  `replica/clone-screens/` (`replica-diff/SKILL.md:50-54`; `replica-build/SKILL.md:57-58`). Screenshots
  are taken by the user or a connected browser tool. The pack ships no capture script [F], and
  `replica-test` only says to drive a browser tool "if available" (`replica-test/SKILL.md:58-60`).
- **`imgdiff.py` layout mode** [F]: a colour-invariant structural comparison.
  - Images are converted to luminance (`imgdiff.py:230-231`), then to a binary edge map: a pixel is
    an edge if `|right - here| + |below - here| > 40` (`:234-246`).
  - The image is cut into a 12-column grid of square cells (`:334-336`). Each cell's edge density
    is compared as `1 - |da - db| / max(da, db)`, and cells empty in both are skipped "so empty margins
    do not pad the number" (`:345-351`).
  - The score is the mean similarity (`:358`). Cells under 0.6 are flagged, flood-filled into
    regions, and reported in the **original's** pixel coordinates with coarse labels such as
    "bottom left" (`:249-272,360-382`).
  - The height difference is reported separately, not hidden (`:287,402-405`).
  - Verdict bands: matches ≥ 90, close ≥ 75, partly ≥ 50, otherwise different (`:385-392`).
  - Tests demonstrate colour invariance (rebrand ≥ 90 layout while the pixel score falls) and
    localisation of a moved element (`test_imgdiff.py:145-162`).
- **Pixel mode** [F] (`imgdiff.py:300-330`) is a per-channel tolerance diff, explicitly intended
  for the clone's own regressions, not for the original (`replica-diff/SKILL.md:67-68`).
- **Limitations** [I]:
  - Per-cell edge **density** is position-insensitive within a 40 px cell (at 480 px width) and
    content-insensitive. Different text or icons with similar edge density score as matching.
  - Nearest-neighbour resampling (`imgdiff.py:215-219`) can alias thin lines.
  - Only the shared height is compared (`:284-286`).
  - Luminance edges are not fully colour-invariant: a rebrand that pushes a contrast boundary across
    the threshold of 40 changes the edge map.
  - The 0.6 flag threshold and 40 edge threshold are uncalibrated constants, and no
    ground-truth set exists [F: no calibration data in the repo].
- **Diff image** [F]: a dimmed greyscale of the original with differing cells tinted red
  (`imgdiff.py:291,353-357`), written as an 8-bit RGB PNG by a stdlib encoder (`:194-210`).

### 11.5 Feature-parity measurement

- **`parity.py`** [F]:
  - Weights must 3, should 2, could 1 and credits yes 1, partial 0.5, no 0 (`parity.py:36-37`).
    P0/P1/P2 are accepted as synonyms (`:36`).
  - It excludes `skip` and `original=no` rows so that "the number only ever measures parity"
    (`:22-24,75-80`).
  - Outputs: the feature score; must-haves done of total; per-area scores weakest first; the missing
    list sorted by weight desc, then credit asc, then area and name, "in build order" (`:107-108`);
    skipped rows with reasons ("no reason given, add one", `:185`); extras; and matrix problems
    reported as non-fatal (`:81-86,196-200`).
  - With `--visual`, overall = 0.8 × features + 0.2 × mean layout, since "Features are what users pay
    for" (`:26-28,143-151`). `--fail-under` gates on the **overall** score (`:222-223`).
- **Verdict rubric** (LLM-applied) [F]: not shippable if any must-have is missing or any S1 is open;
  shippable at all must-haves, 80+, no S1/S2; "better than the original" when it is shippable and
  the entrepreneur fixes are in. "This is the goal. A straight copy has no reason to exist"
  (`replica-diff/SKILL.md:79-87`).
- **Behaviour diff** (manual) [F]: clicks to finish the core flow, error handling, persistence and
  emails, written as flow / original does / clone does / fix or keep (`replica-diff/SKILL.md:70-75`).
- **Limitations** [F/I]:
  - The `clone` column is self-reported by the building session (`replica-build/SKILL.md:56`) and
    is not linked to passing tests, so the score measures claimed parity, not verified parity [I].
  - `partial` is a flat 0.5 whatever the degree.
  - The deploy preflight runs `parity.py` without `--fail-under`, so it cannot fail on missing
    must-haves by exit code (`replica-deploy/SKILL.md:33`; `parity.py:218-224`) [F].
  - The layout component rewards structural similarity to the original, the same property the
    design skill calls trade dress (`replica-design/SKILL.md:36-37`). It is capped at a 20% weight,
    and the skill says not to chase pixels (`replica-diff/SKILL.md:30-32`), but the incentive is not
    zero [I].

### 11.6 Differentiation from competitor evidence

This step goes beyond replication [F]. Review mining with **provenance enforced in code**:
- rows without an http(s) URL are dropped and counted (`reviews.py:104-106,223-225`);
- quotes are always verbatim substrings, ellipsised only at the edges (`:138-150`; asserted by
  `test_reviews.py:69-76`);
- the thin-evidence flag (`:196`) and the small-sample warning (`:228-231`);
- surfaced "read by hand" unthemed negatives (`:260-269`).

The output feeds positioning statements that carry evidence counts
(`replica-entrepreneur/SKILL.md:96-102`) and becomes `original=no` rows in the matrix. Limitation
[I]: the regex themes are coarse and multi-label. For example "reminders" sits in the
*notifications complaint* theme (`themes.json:36`), so a request such as "I wish it had SMS reminders"
also counts as a notifications complaint.

### 11.7 Identity separation (anti-copy verification)

- `sweep.py` [F] does case-insensitive name matching across separators and inside identifiers
  (`sweep.py:51-59`), domain literals (`:60-63`), and hex colours normalised from short to long form
  (`:40,44-48,119-124`). It checks file and folder names (`:92-106`) and exits 1 on any hit.
- **Limits** [F/I]:
  - Colours only as `#rgb`/`#rrggbb`. `rgb()`, `hsl()`, Tailwind palette names and hex without `#`
    are silently ignored, and non-hex `--colors` values are dropped (`:79`) [F].
  - Binary files, including PNG logos and fonts, are skipped (`:37-39,108`), so copied raster assets
    or font files are not detected [F].
  - No check for copied copy text, SVG path data or CSS.
  - Substring matching on short names (for example a three-letter brand) will produce false
    positives on ordinary words, and there is no allowlist [I].
- `listing.py` [F]: uses word-bounded `avoid` matching (`listing.py:95`), stricter than `sweep.py`.
  A store listing containing "CalendlyAlternative" would pass `listing.py` but fail `sweep.py` [I].
  The `--avoid` CLI value **replaces** the file's `avoid` list rather than merging (`:72`) [F].
  `listing.py` does not read `brand.json`, so `avoid` must be duplicated into `listing.json`
  (`listing.example.json:2`) [F].

## 12. Innovations

1. **Feature matrix as a single cross-stage ledger with scoring semantics.** One CSV is created by
   recon, mutated by build, backend and entrepreneur, and scored by `parity.py`, with `skip`
   (deliberate non-goal) and `original=no` (differentiator) kept apart from parity
   (`replica-recon/SKILL.md:111-122`; `parity.py:66-127`). The scope boundary and the "better than
   the original" goal become measurable data instead of prose.
2. **Colour-invariant layout diff.** Edge-density grid comparison means a deliberate rebrand does not
   lower visual parity, while structural drift is still localised in the original's coordinates
   (`imgdiff.py:275-374`; `test_imgdiff.py:145-162`). It is implemented with a dependency-free PNG
   codec (all filter types, palette, 16-bit, alpha).
3. **Provenance enforced in code for LLM-assisted research.** `reviews.py` cannot emit a claim
   without a source URL and cannot paraphrase: quotes are substrings of the input rows, and thin
   evidence and small samples are flagged automatically (`reviews.py:22-25,104-111,138-150,196,228`).
   This structurally guards against fabricated evidence in agent output.
4. **Evidence and confidence on inferred models.** Each inferred entity carries the screens or
   articles it came from and a high / medium / guess confidence (`replica-recon/SKILL.md:98-109`).
   The epistemic status survives into architecture.
5. **Rules before workflow, plus "to run vs dated result" for external checks.** Every skill puts its
   ethical and legal constraints before the steps. Unexecuted checks must be written as "to run",
   never as "available" (`replica-brand/SKILL.md:42-43`), which is a guard against hallucinated
   verification.
6. **Tool-backed preflight composed from the upstream skills' tools.** The deploy gate reuses the
   upstream tools' exit codes (`replica-deploy/SKILL.md:27-48`). It is only partially mechanical:
   see the `parity.py` exit-code gap in section 5.
7. **Role-and-label E2E selectors chosen so the tests survive the rebrand**
   (`e2e.example.spec.ts:2,18-23`), with console-error, 5xx and axe failure hooks (`:7-14,25-26`).

## 13. Reusable components

All components are MIT (`LICENSE`), © 2026 Jake Schincariol; the notice must be kept.

| Component | Path | Kind | Dependencies | License | Security notes | Reuse class | Limits and compatibility constraints |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Layout and pixel screenshot diff + stdlib PNG codec | `replica-diff/imgdiff.py` | script/library | Python 3 stdlib | MIT | Unbounded `zlib.decompress` (`:152`); uncaught `struct.error` on truncated IHDR (`:127`, issue #10) | directly reusable | PNG only, non-interlaced; slow and memory-heavy on large images (full decode before downscale); uncalibrated thresholds; density-only per cell |
| Weighted feature-parity scorer | `replica-diff/parity.py` | script | stdlib | MIT | None notable | directly reusable | Fixed CSV schema; flat 0.5 partial credit; exit code gates only with `--fail-under` on the overall score; no must-have exit code |
| Feature-matrix schema (must/should/could, original, clone, skip+reason) | `replica-recon/features.csv` | pattern/template | none | MIT | n/a | reimplement the idea | Self-reported status; no link to tests |
| Provenance-enforcing evidence ranker | `replica-entrepreneur/reviews.py` + `themes.json` | script + config | stdlib | MIT | Ingests untrusted third-party text that the LLM later reads (injection surface); user-supplied regex | needs adaptation | Regex themes are English-only, coarse and multi-label; case-sensitive URL check (`:104`) |
| Denylist identity sweep (names inside identifiers, domains, hex colours) | `replica-brand/sweep.py` | script | stdlib | MIT | Reads the whole tree (≤ 2 MB per file); no symlink following | needs adaptation | Hex-only colours; binaries skipped; substring false positives; root-only `replica/` skip |
| WCAG contrast gate over design tokens | `replica-design/contrast.py` | script | stdlib | MIT | None | directly reusable | WCAG 2 relative luminance only (not APCA); hex only; nested `value`/`$value` tokens supported |
| Store-listing linter | `replica-launch/listing.py` | script | stdlib | MIT | Literal invisible Unicode in source (`:50,53`) | needs adaptation | Store limits hard-coded (`:31-35`) and may drift; claims regex heuristic; word-bounded name matching |
| Recon map template with stable S/F IDs, states, evidence + confidence | `replica-recon/recon-map.md`, `replica-recon/SKILL.md` | template/skill | none | MIT | Skill reads untrusted web content with no data-not-instructions guidance | reimplement the idea | Assumes a single web/mobile app; no automated capture |
| Clean-room and ToS rules block | `replica-recon/SKILL.md:26-45`, `replica-build/SKILL.md:18-27`, `replica-design/SKILL.md:23-37` | pattern | none | MIT | Prose only; no enforcement | reference only | Omits patents, public-site ToS, retention of captured material; not legal advice |
| Test-plan and bug-report formats (F01-H1/E/N IDs, S1–S4) | `replica-test/test-plan.md`, `bug-report.md` | template | none | MIT | n/a | directly reusable | Generic |
| Playwright spec skeleton with console, 5xx and axe guards | `replica-test/e2e.example.spec.ts` | template | `@playwright/test`, `@axe-core/playwright` (unpinned) | MIT | Unpinned npm install in skill text | needs adaptation | Booking-app specific selectors |
| Deploy preflight checklist | `replica-deploy/preflight.md`, `SKILL.md:27-48` | workflow/template | the tools above | MIT | LLM-enforced gate; relative path ambiguity | reimplement the idea | `parity.py` and the by-hand items are not exit-code gated |
| "to run vs dated result" external-check rule | `replica-brand/SKILL.md:40-57` | pattern | none | MIT | Guards against hallucinated verification | reimplement the idea | Prose only |

## 14. Evidence against the value dimensions

**Engineering quality.** The six tools are small and readable, with clear docstrings, consistent
exit-code contracts (0/1/2) and 57 unit tests. The tests include an independent PNG encoder and
property-style checks such as rebrand invariance and quote-substring provenance (section 7)
[demonstrated by reading; not executed]. Weaknesses: there is no CI, and two input-validation defects
are confirmed by code reading (IHDR `struct.error`, case-sensitive URL check). Repo-shape tests
hard-code copy, and the skills have no eval or trigger tests (sections 7, 4). The README's numeric
walkthrough (`README.md:100-106`) is illustrative and backed by no fixture [claimed].

**Autonomy and orchestration.** The pack has no orchestration code, agents, parallelism or retries.
The user drives the 11 steps and the LLM interprets each SKILL.md (section 5). Human gates
exist for scope, credentials and deploy "go" [demonstrated in prose]. Autonomy is deliberately low.
The pipeline is a file-handoff methodology, not an autonomous factory.

**Development productivity.** The ID-keyed specification (screens, flows, entities with evidence) and
the feature-matrix ledger give a structured path from an existing app to a build order, and the tools
replace subjective "how close are we" judgements with numbers (sections 6, 11). Claimed outcomes, such
as "A booking tool is weeks" (`README.md:177`), are not evidenced in the repo. No end-to-end run
artifacts are included.

**Security and reliability.** The pack has strong *stated* boundaries on account use, scraping,
private APIs, asset copying, fabricated evidence, credentials and deploy approval (section 8 table).
Enforcement is limited: three tools check names, domains, colours, store metadata and review
provenance, and everything else is prose with no hooks or tool restrictions. Gaps: no
data-not-instructions guidance for untrusted web and review content; patents and public-site ToS not
addressed; no retention guidance for captured screenshots and reviews; the deploy preflight's parity
step does not fail by exit code (sections 5, 8). The tools themselves are network-free and
subprocess-free [verified by grep].

**Maintainability and adaptability.** Skills are plain Markdown with a uniform structure. Tools are
stdlib-only with no dependencies, and templates and `themes.json` are editable (sections 4, 13). Risks:
there is a single maintainer and commit with 12 unmerged issues/PRs. PR #4 claims `"skills": "./"` is
rejected by Claude Code's loader, but the current official plugins reference says both `"."` and `"./"`
denote the plugin root for `skills` (only `"."` failed validation before v2.1.221) [F docs:
code.claude.com/docs/en/plugins-reference, accessed 2026-10-22; not executed]. The
preflight uses sibling-relative tool paths, and `test_repo.py` pins exact README copy.

**Resource efficiency.** The always-loaded footprint is moderate (about 5.7k characters of
descriptions across 11 skills) and there is no progressive disclosure beyond templates (section 9).
Deterministic tools keep heavy computation out of the context window. `imgdiff.py`'s pure-Python full
decode is CPU- and memory-inefficient on retina screenshots [inferred, not executed]. The pack has no
model routing or cost controls.

## 15. Strengths and limitations

**Strengths**
- The specification has stable IDs, enumerated UI states, evidence and confidence on inferred data,
  and explicit non-goals (`replica-recon/SKILL.md:71-122`).
- One ledger (`features.csv`) links specification, build progress, parity score and differentiators
  (`parity.py:66-127`).
- The layout diff is colour-invariant and localises structural drift; it is tested
  (`imgdiff.py:275-374`; `test_imgdiff.py:145-162`).
- Code makes fabricated evidence impossible in `reviews.py` output (`reviews.py:104-111,138-150`;
  `test_reviews.py:69-76`).
- Clear, upfront legal and ethical rules on every skill, with honest disclaimers
  (`README.md:156-186`).
- Credentials and spending are reserved to the human; deploy needs an explicit go
  (`replica-backend/SKILL.md:22-25`, `replica-deploy/SKILL.md:20-24`).
- Zero-install, network-free tooling (`README.md:121`; grep of imports).
- Good testing advice for the produced software: TDD fix loop, role selectors, console/5xx/axe
  guards, second-user RLS test (`replica-test/SKILL.md`, `e2e.example.spec.ts`,
  `replica-backend/SKILL.md:42-43`).

**Limitations**
- The "enforcement" is mostly prose. No hooks, `allowed-tools` or sandbox (section 8). The README's
  "the skills enforce it" overstates it (`README.md:17`).
- The parity score rests on self-reported `clone` values, and the deploy preflight cannot fail on
  missing must-haves by exit code (`replica-build/SKILL.md:56`; `parity.py:218-224`;
  `replica-deploy/SKILL.md:33`).
- "Clean room" has no role or session separation between whoever sees the original and whoever writes
  the code (section 3).
- There is no prompt-injection guidance, although the pipeline ingests untrusted web pages and review
  text (`replica-recon/SKILL.md:58-69`; `replica-entrepreneur/SKILL.md:44-60`).
- Legal coverage gaps: patents, public-site ToS, copyright named only implicitly, no retention
  guidance for screenshots and reviews, no refusal conditions (section 8).
- `sweep.py` misses binary assets, non-hex colours and copied text (`sweep.py:37-40,79,108`).
- Maintenance: a single commit, no CI, and an unmerged crash fix (#12 for #10). PR #4 disputes the
  plugin layout, but current official docs accept `"skills": "./"` (section 16), so this is at most a
  risk on older Claude Code versions [I].
- The broad recon trigger ("how does X work") and no negative triggers (`replica-recon/SKILL.md:7-10`).
- No screenshot capture tooling. Capture is manual or depends on an optional browser tool
  (`replica-test/SKILL.md:58-60`).

## 16. Claims vs verified ledger

| Claim (source) | Status | Evidence |
| --- | --- | --- |
| "Eleven Claude skills" (`README.md:3`) | verified | 11 `replica-*/SKILL.md`; `test_repo.py:23-26` |
| "Free, MIT" (`README.md:3`, `plugin.json:11`) | verified | `LICENSE`; `gh api` license MIT |
| "no signup, no API key, nothing to connect" (`README.md:3-4`) | verified (for the pack) | No network code; the clone's backend does need user accounts (`replica-backend/SKILL.md:22-25`) |
| "Six of them, all standard-library Python. None touch the network." (`README.md:121`) | verified | 6 `.py` tools; imports grep shows no urllib/http/socket/subprocess |
| "The tools need Python 3.8 or newer. Nothing to pip install." (`README.md:50`) | partly | Stdlib only (verified); 3.8 compatibility not executed; PR #3 claims 3.8–3.14 pass [C] |
| "the skills enforce it" (`README.md:17`) | partly | Prose rules; mechanical checks only via `sweep.py`, `listing.py`, `reviews.py`; no hooks or tool limits |
| "It only reads what you are allowed to read … never scrapes behind a login or against a site's terms" (`README.md:163-167`) | not executable | Prose in `replica-recon/SKILL.md:32-43`; public-site ToS check absent; no technical control |
| "/replica-deploy will not ship until the sweep is clean" (`README.md:169-170`) | partly | `sweep.py` exits 1 (`:173`); deploy instruction `replica-deploy/SKILL.md:25,34`; LLM-enforced |
| `imgdiff.py` "reads PNGs with no libraries … new colours do not count against you" (`README.md:132-134`) | verified (code + tests, not executed) | `imgdiff.py:107-181,230-246`; `test_imgdiff.py:145-152`; luminance edges are not perfectly colour-invariant [I] |
| "Retina and non-retina screenshots compare fine" (`replica-diff/SKILL.md:65`) | verified (test) | `imgdiff.py:222-227,280`; `test_imgdiff.py:170-175` |
| `parity.py` "Missing must-haves means not shippable, and it says so" (`README.md:136-138`) | partly | Says so in text (`parity.py:165-168`); exit code stays 0 without `--fail-under` (`:218-224`) |
| `reviews.py` "drops every review without a link. Every quote … copied from a row you gave it" (`README.md:140-142`) | verified | `reviews.py:104-106,138-150`; `test_reviews.py:57-60,69-76` |
| "Themes with under three reviews or one source are marked thin" (`README.md:142`) | verified | `reviews.py:196`; `test_reviews.py:83-85` |
| `sweep.py` finds names "including inside identifiers … and blocks the deploy" (`README.md:144-146`) | partly | Identifier match verified (`sweep.py:57-59`; `test_sweep.py:51`); "blocks" is exit 1 run by the LLM |
| `listing.py` flags "the original's name anywhere in your listing" (`README.md:148-150`) | partly | Word-bounded match (`listing.py:95`) misses embedded names such as "XAlternative" [I] |
| `/replica-diff` "gives you a real number, not a vibe" (`README.md:178-179`) | partly | Deterministic maths over self-reported `clone` values (`replica-build/SKILL.md:56`) |
| "/replica-recon sizes it honestly before you start" (`README.md:177-178`) | not executable | Instruction only (`replica-recon/SKILL.md:124-128`) |
| Plugin install via `/plugin install replica-skill@replica-skill` (`README.md:31-34`) | not executable; PR #4 claim contradicted by current official docs (not executed; may reflect an older version) | `plugin.json:21` `"skills": "./"`; PR #4 claims the loader rejects it with "Path escapes plugin directory" [C]. The plugins reference says for `skills` "Both `"."` and `"./"` denote the plugin root", that `"."` failed validation only before v2.1.221 (so `"./"` is the safe form), and that `skills` adds to the default `skills/` scan [F docs: code.claude.com/docs/en/plugins-reference, accessed 2026-10-22] |
| Walkthrough figures ("Features 86 … layout 91", "140 real reviews") (`README.md:100-106`) | not found | No fixtures or run artifacts in the repo; illustrative |
| FTC 2024 rule makes fake reviews illegal in the US (`replica-entrepreneur/SKILL.md:39-40`) | not verified (outside repo scope) | No primary source checked |
| Apple Guideline 4.1 (Copycats) rejects copy apps (`replica-launch/SKILL.md:80-83`) | not verified (outside repo scope) | No primary source checked |
| Store field limits (name 30, subtitle 30, promo 170, keywords 100, description 4000; Play 30/80/4000) (`listing.py:31-35`) | not verified (outside repo scope) | Hard-coded constants |
| 57 tests (PR #3 body) | verified (count) | `grep -c 'def test_'` = 57; pass status not executed |

## 17. Uncertainties and research completeness

**Could not check, and why:**
- Whether the tests pass, how fast `imgdiff.py` runs on real screenshots, and Python 3.8
  compatibility. Running repository code is prohibited by the brief.
- Whether Claude Code's plugin loader accepts `"skills": "./"` at run time (PR #4 claim). The current
  official plugins reference says it does (section 16); the loader itself was not executed, and the
  Claude Code version PR #4's author used is unknown [U].
- How well the skills behave in practice: trigger accuracy, whether an LLM actually honours the rules,
  the quality of produced clones. There are no eval artifacts or transcripts in the repo.
- Legal accuracy of the cited rules (FTC, Apple 4.1, store limits). These are outside repository scope,
  and no primary legal sources were consulted.
- Maintainer responsiveness. Issue and PR comments were not read; only titles and four bodies (#3,
  #4, #7, #10). Issues #5, #8, #9, #11, #13 look like noise by title [U].

**Completeness rating: complete.** The repository is small (39 tracked files, about 4,000 lines), and
every file was read in full: README, 2 manifests, `.gitignore`, LICENSE header, 11 SKILL.md, 11
templates/configs, 6 tools, 7 test files. Additional checks: grep for hidden or bidi Unicode, secrets,
network/exec imports and legal terms; `gh api` metadata (repo, branches, releases, tags, commits,
Actions runs, issues/PRs). Nothing was skipped. No branches beyond `main` exist, so none were cloned.

### Verification corrections (2026-10-22)

- V11-1: §1, §14, §15, §16, §17 — PR #4's claim that `"skills": "./"` is rejected ("Path escapes plugin directory") is now recorded as contradicted by the current official plugins reference (code.claude.com/docs/en/plugins-reference, accessed 2026-10-22): both `"."` and `"./"` denote the plugin root for `skills`, only `"."` failed validation before v2.1.221, and `skills` adds to the default `skills/` scan. Not executed; PR #4 may reflect an older version. The "disputed plugin layout" limitation was downgraded accordingly. The finding's cited lines ~435-436 hold no PR #4 text in this report (§9 efficiency); every other cited location was updated.
- N3-2 (verifier, closure pass): the legend now defines the [F docs] tag used in this report.
