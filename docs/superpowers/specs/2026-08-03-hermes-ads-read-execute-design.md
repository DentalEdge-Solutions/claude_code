# Hermes read-execute for `claude-google-ads` — Design Spec (P5 Track B.1 / Increment 3)

> **Status:** DRAFT for review. Supersedes the roadmap's one-line Increment 3
> (`docs/superpowers/plans/steady-discovering-hartmanis.md`), whose safety model
> and credential premise are corrected here (see §1). No implementation begins
> until this spec is reviewed and its Prerequisites (§9) are provisioned.

## 0. One-paragraph summary

Give Hermes its first *execute-with-live-credentials* capability against the
`claude-google-ads` project — running that project's **reporting/read** scripts
with **real Google Ads credentials but provably zero mutation**. Execution lives
in a tested Python **runner** that invokes only allow-listed reader scripts (the
Inc-1 "fat engine, thin skill" pattern); `claude` stays strictly read-only and
never gets a shell. Mutation is made impossible at the **platform layer** by
running under a **read-only Google Ads credential**, so even a bug or injection
cannot change the live account. This is the on-mission first step toward the
commercial pilot (canon D-5): `claude-google-ads` is itself a downstream
`./install.sh` target of this toolkit, and this increment lets the control plane
operate it end-to-end.

## 1. What changed from the roadmap's Increment 3 (and why)

The roadmap wrote Increment 3 as a single line. Three of its assumptions do not
survive contact with the target and are corrected here — two of them fail in the
exact ways Increments 1–2 taught us to expect:

| Roadmap assumption | Correction | Precedent |
|---|---|---|
| "mutation attempt **refused by policy**" | Backstop must be **platform-enforced** (read-only Google Ads credential), because "refused by policy" is the "won't be asked to" posture we rejected in Inc 2. Our allow-list is a *second* layer, not the guarantee. | Inc 2: the branch **ruleset**, not our guard, was the real backstop. |
| "credentials stay in the gitignored `.env`, **out of tree** … nothing sensitive is mounted" | **False today** — the live `.env` is physically in the project dir, so the `:ro` bind mount exposes it inside the container. Verified directly. Credentials are delivered **per-invocation instead**, and the in-tree `.env` is neutralized (§5). | Inc 2 Task 1: the "operator-only via env-scrub" premise was also empirically false. |
| "read-**execute**" treated as a small step from `read` | It is a **new confinement tier**. Today's `read` scope is plan-mode + `Read/Grep/Glob` and cannot run Python at all; executing reporters reintroduces subprocess execution — the surface Inc 1 spent its design forbidding. Handled by keeping execution in a tested runner, **not** by giving `claude` Bash. | Inc 1: the confinement core was *no* terminal/exec. |

Framing note: `claude-google-ads` is **not** an unrelated external codebase. It is
the pipeline's first real `install.sh` target and the intended commercial pilot.
Integrating with it is on-mission; the only genuine coupling risk is ordinary
in-development churn, handled by **pinning** exactly which scripts we execute.

## 2. Goal & non-goals

**Goal.** `run-ads-report.sh --project claude_google_ads --report account_overview`
produces a real, credential-scrubbed Google Ads read report on disk under
`/opt/data`, executed under a read-only credential, with the target project and
the live account both provably unmutated.

**Non-goals (this increment):**
- No mutation capability of any kind (that is a later, separately-gated step).
- Not all 14 readers — a **thin pinned slice** (`test_connection`, `account_overview`).
- No changes to the `claude-google-ads` repo. All artifacts are Hermes-side.
- No new LLM autonomy: `claude` gains no new tools; execution is the runner's.

## 3. Threat model — why this is the highest-risk increment so far

Inc 1 and Inc 2 ran *our* code against *our* repo. Inc 3 runs *reporting code* with
*live client credentials* against a *real Google Ads account*. The assets to
protect, worst first:

1. **The live Google Ads account** — an accidental or injected mutate. → Layer 1
   (read-only credential) + Layer 2 (allow-list) + Layer 3 (no shell for `claude`).
2. **The credentials themselves** — leaking into logs, reports, telemetry,
   transcripts, or memory/brain (Hard Rule). → Layers 4–6 + the scrub + the scan gate.
3. **The target's integrity** — writes to the `:ro` mount. → Layer 7.

## 4. Architecture — fat runner, read-only model

```
operator / hermes cron
   └─ run-ads-report.sh (host)            # sources .env.ga; injects creds per-invocation
        └─ docker compose exec -e GOOGLE_ADS_* -T hermes-agent \
             python3 /opt/cc-bin/run-ads-report.py --project P --report R
                 ├─ resolve scope+allow-list from /opt/registry/projects.yaml   (Layer 2)
                 ├─ refuse if R not in read_execute allow-list  (fail-closed)   (Layer 2)
                 ├─ run pinned reader:  python3 <workdir>/code/<R>.py
                 │     cwd = scratch (no .env discoverable)                      (Layer 5)
                 │     env = injected read-only GOOGLE_ADS_* only                (Layers 1,4)
                 ├─ scrub all six GOOGLE_ADS_* values from stdout/stderr         (Layer 6)
                 └─ persist scrubbed report → /opt/data/reports/<project>/<ts>-<R>.md
   (optional, later) claude -p  --allowedTools 'Read,Grep,Glob' --permission-mode plan
        summarizes the PERSISTED report — read-only, no creds, no shell          (Layer 3)
```

**Key property:** the "execute" capability is the runner's, expressed in tested
Python with an explicit allow-list. `claude` never runs a subprocess, so the
known Hermes gap (arbitrary-named secrets are *not* scrubbed from agent-launched
subprocess env — the Inc-2 finding) is never reachable from a prompt.

## 5. Components

### 5.1 `read-execute` scope + allow-list (registry)
Add to `registry/projects.yaml` on the `claude_google_ads` entry:
```yaml
    scope: read-execute            # NEW tier: run allow-listed reader scripts only
    read_execute:
      runner: python3
      script_dir: code             # relative to workdir
      allow:                       # EXACT basenames; fail-closed; readers ONLY
        - test_connection
        - account_overview
      # mutators are simply absent → unreachable (apply_negatives, add_campaign_negative,
      # add_competitor_negatives, attach_audience)
```
The operator skill gains a `read-execute` branch: it **must not** run scripts
outside `allow`, **must not** grant `claude` Bash/Edit/Write, and routes execution
to the runner — never to `claude -p`.

### 5.2 `bin/run-ads-report.py` (+ `.test.py`) — the engine
- Stdlib-only. Resolves the project + `read_execute` config from the registry
  (reuse/extend the Inc-2 `read_pr_target` hand-parser discipline).
- **Fail-closed allow-list:** `--report R` must be an exact member of `allow`;
  reject bare-filename violations / path separators (the Inc-2 traversal fix).
- Requires the complete injected credential set present in env; refuses if any of
  the six `GOOGLE_ADS_*` vars is missing (so nothing falls through to `.env`).
- Runs `python3 <workdir>/<script_dir>/<R>.py` with **cwd = an empty scratch dir**
  so `load_dotenv()` discovers no `.env`; passes only the injected read-only env.
- `_scrub()` removes every one of the six credential values from captured
  stdout+stderr before persist or print (belt-and-suspenders; values should never
  appear, but a stack trace could echo an id).
- Persists the scrubbed report to `/opt/data/reports/<project>/<UTC-ts>-<R>.md`
  and prints the path. Non-zero exit on runner failure with a scrubbed message.

### 5.3 Credential delivery — `.env.ga` (gitignored)
- `infra/hermes-agent/.env.ga` holds the **read-only** credential set (§9). It is
  **not** referenced by `env_file` in `docker-compose.yml` and is **not** in the
  gateway env — identical to the Inc-2 `.env.pr` treatment.
- `run-ads-report.sh` sources `.env.ga` and passes the six vars via
  `docker compose exec -e GOOGLE_ADS_DEVELOPER_TOKEN -e … -T`. Add `.env.ga` to
  `.gitignore`; ship `.env.ga.example` (placeholders only).
- **Why injection wins over the in-tree `.env`:** the target's scripts call
  `load_dotenv()` (default `override=False`) then `os.getenv()`. A var already in
  the environment is **not** overwritten by `.env`. Injecting the full set +
  running from a no-`.env` cwd means the in-tree full-access token is never used.

### 5.4 Platform backstop — read-only Google Ads user (§9 prerequisite)
The refresh token in `.env.ga` belongs to a Google account granted **Read-only**
access to the MCC/client. Any mutate then returns `USER_PERMISSION_DENIED` at the
API — the guarantee that survives our bugs, `hermes update`, and the VPS.

### 5.5 Output persistence + scan
Reports land under `/opt/data/reports/<project>/` (dated, mirrors the proposals
convention). A credential scan step (grep the six values across
`/opt/data/logs`, `/opt/data/reports`, `docker compose logs`, telemetry) is part
of acceptance and returns clean.

## 6. Guardrail stack (the 7 layers)

1. Platform read-only credential → server refuses mutation.
2. Runner allow-list, fail-closed → only readers run; mutators unreachable.
3. `claude` never gets Bash/Edit/Write → the unscrubbed-env gap is unreachable from a prompt.
4. Creds per-invocation, out of the gateway env and `env_file` (`.env.ga` + `-e`).
5. In-tree `.env` neutralized → full injected set + no-`.env` cwd.
6. `_scrub()` on all captured output before persist/print.
7. `:ro` project mount → runner writes only under `/opt/data`.

## 7. Task-1 verification gate (controller-run, empirical, BEFORE build)

No construction until these pass, using the read-only credential — with a
**permission-denied-vs-config-error discriminator** (don't read a missing prereq
as a broken capability, the Inc-2 Step-3 false-positive lesson):

- **G1 — mutation refused server-side.** A `validate_only`/minimal mutate under the
  read-only credential returns `USER_PERMISSION_DENIED` (authorization), *not* a
  config/auth error. Positive control first: confirm a read query succeeds with
  the same credential, so the refusal is proven to be permission-scoped.
- **G2 — `.env` exposure mapped.** Determine empirically whether the in-tree
  `.env` is readable inside the container and by `claude`'s Read tool; record the
  residual (§10).
- **G3 — injection dominates.** With the full read-only set injected and cwd = a
  no-`.env` dir, confirm the reader uses the injected credential and **no** var
  falls through from the in-tree `.env`.
- **G4 — one reader end-to-end.** `test_connection` (then `account_overview`) runs
  read-only and produces real output; `git status --porcelain` on the target is
  byte-identical before/after.
- **G5 — scan clean.** No credential value appears in logs/report/transcript.

## 8. Acceptance criteria

- A real `account_overview` report exists under `/opt/data/reports/claude_google_ads/`,
  credential-scrubbed.
- A mutate attempt under the credential is refused **server-side** (evidence captured).
- The runner **refuses** a report name not in `allow` and refuses path-separator input.
- `claude` in this flow has **no** Bash/Edit/Write (resolved tool set shows read-only).
- `:ro` mount byte-identical; no writes outside `/opt/data`.
- Credential scan across logs/reports/telemetry/transcripts is clean.
- All new scripts ship `.test.py`; suite green (offline: allow-list fail-closed,
  scrub, missing-var refusal, traversal reject, registry parse).

## 9. Prerequisites (operator-provisioned, at gate time — like Inc 2's org-move + PAT)

1. **Read-only Google Ads user + refresh token.** Invite a Google account with
   **Read-only** access to the MCC/client; run the OAuth flow (`get_refresh_token.py`)
   for that account; place its `GOOGLE_ADS_REFRESH_TOKEN` and the account/customer
   IDs into `infra/hermes-agent/.env.ga`. The developer token stays the same
   (MCC-scoped). Do **not** create anything until this spec is reviewed.

## 10. Residual risks (honest notes, Inc-1 style)

- **In-tree full-access `.env` visible `:ro` in the container.** The credential
  actually *used* is read-only (§5.3–5.4), and `claude` has no shell to read the
  file, but the full-access token remains as exposed inside the container as it is
  on the host. Mitigations, in order of preference: (a) get the target to move
  `.env` truly out of tree (longer-term, owner's call); (b) a more specific mount
  that excludes `.env`; (c) accept for a loopback single-operator container and
  verify `claude` never reads it (transcript scan). Decision recorded at review.
- **In-development target churn.** A renamed/added reader silently drops off the
  allow-list (fail-closed = safe) or requires an allow-list update. Acceptable;
  the allow-list is the intended pin point.

## 11. Scope boundary & follow-ons

- **This increment:** the `read-execute` tier + runner + two pinned readers + gate.
- **Cheap follow-on (3b):** broaden `allow` to the full reporting suite once the
  pattern is proven.
- **Explicitly out (later, separately gated):** any mutator; LLM-driven report
  selection with tools; the domain-specialist review team (roadmap Inc 5).

## 12. Global constraints (bind every task)

- Stdlib-only in `run-ads-report.py`; no changes to the `claude-google-ads` repo.
- Read-only credential is the mutation backstop; allow-list is the second layer.
- Creds never in the gateway env, `env_file`, git, logs, reports, telemetry, or
  memory/brain; `.env.ga` gitignored; `_scrub()` on all captured output.
- `claude` never receives Bash/Edit/Write in this flow.
- `:ro` mount never written; runner writes only under `/opt/data`.
- Delivered via subagent-driven-development: Task-1 gate first (controller-run),
  then TDD tasks with fresh implementer + reviewer, then a final whole-branch review.
