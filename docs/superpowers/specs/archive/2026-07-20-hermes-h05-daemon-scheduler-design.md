# Hermes H0.5 — Daemon + Scheduler (design spec)

> **Date:** 2026-07-20 · **Status:** design (planning only) · **Depends on:** H0
> **Master:** `specs/2026-07-20-hermes-master-architecture.md`

## Goal

Turn the H0 one-shot CLI into a **persistent background process** that runs targets on a schedule
and on demand, with a durable run queue that survives restarts — without changing the H0 run core.
This is the "persistent background orchestrator" identity from the charter, built as a thin
supervisor (master decision **D7**).

## Non-goals (deferred)

Credential vault, HITL, staging/budget enforcement (H1/H2); network-exposed trigger surface
(HTTP/Slack channels — later); VPS deploy (H3). The daemon here is triggered only by its own
scheduler and by a local `hermes enqueue` command.

## Decisions (from master §2, applied here)

- **D3 Persistence:** introduce `hermes/lib/db.js` — a `node:sqlite` wrapper + migration runner —
  and the `runs` table. This is the first phase to need durable state.
- **D2 Runtime:** bump the Docker base to `node:24-slim`, where `node:sqlite` is stable (not merely
  experimental as in 22/23). `scripts/run-all-tests.js` must skip the Hermes DB-dependent suites
  when the host Node version is <22, so contributors on an older host aren't blocked on unrelated
  suites.
- **D7 Daemon:** the daemon is a supervisor loop; the actual execution is the *unchanged* H0
  `loader → runner → result-gate` core, wrapped so it also records lifecycle to the `runs` table.

## Architecture

```
hermes/
├── lib/
│   ├── db.js            # [new] node:sqlite open + migrations (shared infra)
│   ├── queue.js         # [new] enqueue / claim-next / update-status over runs table
│   ├── core.js          # [new] extracted: resolve→run→gate as one callable (from bin/hermes.js)
│   ├── scheduler.js     # [new] parse schedules, compute due jobs, enqueue them
│   ├── loader.js        # [H0, unchanged]
│   ├── runner.js        # [H0, unchanged]
│   └── result-gate.js   # [H0, unchanged]
├── bin/
│   ├── hermes.js        # [H0, refactored to call lib/core.js]
│   └── hermesd.js       # [new] the daemon entrypoint (long-running loop)
├── schedules.json       # [new] cron-like schedule definitions
└── migrations/
    └── 001-runs.sql     # [new] the runs table
```

**Control flow:**

```
hermesd (loop, every TICK_MS):
  1. scheduler.dueJobs(now)  → for each due target, queue.enqueue(target)
  2. job = queue.claimNext()  (atomic: status queued→running)
  3. if job: core.execute(job.target)  → writes run manifest (H0) + updates runs row
  4. queue.finish(job, verdict/exit)   (status → done|failed)
  5. sleep TICK_MS
hermes enqueue <target>  → queue.enqueue(target)      (on-demand path)
hermes run <target>      → core.execute (direct, unchanged H0 behavior, also records to runs)
```

Single-worker by design (one run at a time) — simplest correct model for a single VPS; concurrency
is a later optimization, not needed for v1.

## Scheduling model

`hermes/schedules.json` — declarative, filesystem-as-registry:

```json
{
  "schedules": [
    { "id": "nightly-repo-audit", "target": "repo-audit-testing", "cron": "0 3 * * *", "enabled": true }
  ]
}
```

Cron parsing: a **minimal 5-field cron matcher** written in-house (minute hour dom month dow, with
`*`, `*/n`, and comma lists) — no dependency. The scheduler is stateless about "last run"; it uses
the `runs` table (last `created_at` per schedule target) plus a one-minute tick to avoid double-fire.

## Data model

Uses the master `runs` table (§4). H0.5 owns migration `001-runs.sql`. `status` values used here:
`queued → running → done | failed`. (`awaiting_approval`/`resumed` are H1.)

## Error handling

- **Crash during a run:** on restart, any row stuck in `running` older than a threshold is marked
  `failed` (with a `stale` note) — no silent zombies. (Single worker, so at most one such row.)
- **Scheduler double-fire:** guarded by "already have a run for this schedule in the current
  minute" check against `runs`.
- **DB open failure:** daemon exits non-zero with a clear message (don't run blind without state).
- **A failing target:** recorded `failed`; the daemon continues (one bad target never stops the
  loop). Optional bounded retry (max 1 retry) recorded as a new run row.

## Security

No new external surface: the daemon is triggered only by its own clock and local `enqueue`. No
secrets yet (H1). SQLite file lives under `hermes/state/` (gitignored). Still read-only tier only —
the loader's fail-closed check from H0 is unchanged, so H0.5 cannot run anything H0 couldn't.

## Testing strategy

- **db.js** — migrations run idempotently; re-open is a no-op; schema matches expectation.
- **queue.js** — enqueue then claimNext returns it and flips status atomically; claimNext on empty
  queue returns null; finish sets terminal status; stale-run reaper marks old `running` as `failed`.
- **scheduler.js** — cron matcher unit tests (`*`, `*/15`, lists, dow); `dueJobs` returns only
  enabled+due targets; respects the "already ran this minute" guard (inject a fake `runs` reader).
- **core.js** — executes a target via a stub `claude` (reuse H0's stub trick) and writes both a run
  manifest and a `runs` row.
- **hermesd** — one tick with a fake clock + stub engine drains one queued job to `done`; integration
  test asserts the `runs` row and the run-dir artifact both exist.
- All offline, house style (plain `assert` + manual runner, standalone `node <file>`), wired into
  `run-all-tests.js` (already discovers `hermes/`).

## Definition of done

- Daemon boots, ticks, drains queued jobs, records lifecycle to SQLite; survives restart with queue
  intact; stale `running` rows reaped. All tests green in `run-all-tests.js`. `hermes run` still
  behaves exactly as in H0 (now also recording a `runs` row).
