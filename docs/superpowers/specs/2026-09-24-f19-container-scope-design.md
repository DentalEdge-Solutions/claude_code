# F19 — Container-scoped calls may target only ads-mutator runs (design)

**Status:** approved in sections 2026-09-24; spec awaiting operator review.
**Finding:** F19 in `docs/superpowers/specs/2026-09-21-vps-first-bring-up-findings.md` (found by the
F18 design and whole-branch review). **Gates the kill switch** — confirmed by the assessment in §1.
**Scope:** the proxy's policy for the five id-scoped allow-list entries. Nothing else in the
proxy's parsing, relay or upgrade logic changes.

**Mutation stays disabled throughout. The kill switch is ABSENT and nothing here creates it.**
**The allow-list is not widened.** Its id-scoped entries are narrowed.

## 1. Problem and assessment

`infra/hermes-agent/bin/docker-create-proxy.py`: the id-scoped entries of `ALLOWED` (`:104-108`) —
inspect `GET /containers/<id>/json`, `POST …/start`, `POST …/attach`, `POST …/wait`,
`DELETE /containers/<id>` — match any id (`_ID = [A-Za-z0-9_.-]+`, `:86`), and `decide()` returns
`allowed` for every non-create path as soon as the pattern matches (`:215-216`). Nothing asks
which container the id names.

**The adversary is the broker** — the proxy exists to contain it. Reachable today with **no bug,
only allowed calls**:

| Call | Effect on the Hermes gateway (compose service `hermes-agent`) |
|---|---|
| `GET /containers/json` (allowed) | learn the gateway's id |
| `GET /containers/<gateway-id>/json` | read `Config.Env` — the gateway is started with `env_file: .env`, which holds the Anthropic and Hermes provider keys |
| `POST …/attach?logs=1&stdout=1…` | read its output and log history; with `stdin=1`, write its stdin |
| `DELETE /containers/<gateway-id>?force=1` | kill and remove it (the query string is never inspected) |
| `POST …/start`, `…/wait` | start or block on any container |

`claude-auth-init` also loads `env_file: .env` and is inspectable while its exited container
exists. The create checks do not help: they pin what the broker can **make**, not what it can
**touch**. **Assessment: a real policy gap; it gates the kill switch.**

## 2. Measured facts the design rests on

- **Every id-scoped call on the real rail uses the full 64-hex id.** Box journal of
  `hermes-docker-proxy`, 2026-09-24 (the Phase 6 runs after the F18 rollout), printing only length
  and hex-ness per call (no ids): `3 GET /json 64 hex`, `2 POST /attach 64 hex`,
  `1 POST /start 64 hex`, `1 POST /wait 64 hex`. (Two attaches against one start/wait is most
  likely a run from before that morning's restart; both are 64 hex, which is all this relies on.)
- **All three Compose services share one image**, `hermes-agent-claude` (`docker-compose.yml`:
  `claude-auth-init`, `hermes-agent`, `ads-mutator`). The image cannot tell them apart.
- **The entrypoint can.** Only `ads-mutator` has `["python3", "/opt/cc-bin/apply-changeset.py"]`,
  which is exactly `PINNED_ENTRYPOINT`, already enforced on create. The gateway runs the base image's
  own entrypoint with `command: ["gateway", "run"]` (not measured, but it cannot be
  `apply-changeset.py`: `/opt/cc-bin` is bound only into `ads-mutator`); `claude-auth-init` has
  `/usr/local/bin/bootstrap-claude-auth.sh`.
- **Labels are not a trustworthy signal.** `decide()` does not check `Labels` on create, so the
  broker can label a container it makes however it likes.
- **Compose's list calls filter only by `project=hermes-agent`** (2026-09-16 measurement, rows 2
  and 6), and the gateway is in that project — so no required filter can hide the gateway without
  rewriting the response.

## 3. Decisions (operator, 2026-09-24)

1. **Shape-based, stateless** (over remembering created ids): a container-scoped call is
   forwarded only if dockerd reports the target is shaped like an ads-mutator run. Survives a
   proxy restart; covers a mutator root launches by hand; no create-response parsing.
2. **Full 64-hex id required** in the path — adopted after the §2 measurement.
3. **The list call `GET /containers/json` is left as is**, an explained residual (§8).
4. **The lookup is a fresh upstream connection per check**, via stdlib `http.client`; no cache.

## 4. Design — `bin/docker-create-proxy.py`

### 4.1 Grammar

- New `_CID = r"[0-9a-f]{64}"`. The five container-scoped entries (start, attach, wait, inspect,
  `DELETE`) use `_CID` instead of `_ID`. `_ATTACH_RE` uses `_CID`, so the allow-list entry and
  `_is_attach` still share one object.
- `_ID` remains only for `GET /images/<name>/json`, where the value is an image name.
- A container name, a short prefix, uppercase hex, 63 or 65 characters, or a trailing `/` now
  fails `decide()` as "not on the allow-list", before any lookup.

### 4.2 The rule

An allowed request whose path carries a container id is forwarded only when dockerd's inspect of
that id shows **`Config.Image == PINNED_IMAGE` and `Config.Entrypoint == PINNED_ENTRYPOINT`**.
`Binds` are not compared (they add no distinguishing power here and risk a false refusal if
inspect's formatting differs from create's); labels are not compared (§2).

### 4.3 Units

1. **`container_target(path) -> str | None`** — pure. Strips the query string (`_path_only`), then
   **prefix**-matches `_V + r"/containers/(" + _CID + r")(?=/|\Z)"` and returns the id.
   Deliberately wider than `ALLOWED`: every allowed path that begins with a container id is
   checked, including any id-scoped entry added later. `/containers/json` never matches.
2. **`is_mutator_shaped(doc, cid) -> (bool, reason)`** — pure. Requires: `doc` is a dict;
   `doc.get("Id") == cid`; `doc["Config"]` is a dict; `Config.Image == PINNED_IMAGE`;
   `Config.Entrypoint == PINNED_ENTRYPOINT` (a list; a string or `null` fails). Reasons are fixed
   strings (`"target is not an ads-mutator run: entrypoint mismatch"`, `… image mismatch`,
   `… id mismatch`, `… malformed inspect`), never quoting the document.
3. **`lookup_target(upstream_path, cid) -> (doc | None, reason)`** — the only new I/O. A small
   `http.client.HTTPConnection` subclass whose `connect()` opens an `AF_UNIX` socket to
   `upstream_path`, with timeout `LOOKUP_TIMEOUT = 5` seconds (a module constant tests may lower).
   Sends `GET /containers/<cid>/json` — **unversioned**, so the client's version prefix never
   flows into it — with `User-Agent: hermes-docker-create-proxy-target-check`. Reads at most
   `MAX_BODY + 1` bytes.
   - status 200, body ≤ `MAX_BODY`, JSON parses → `(doc, "")`
   - status 404 → `(None, "target not found")`
   - anything else — other status, oversize body, bad JSON, timeout, `OSError`,
     `HTTPException`, `RecursionError`, **any `Exception`** → `(None, "target lookup failed")`

   Catching `Exception` is deliberate and confined to this unit: an unforeseen lookup error must
   become a refusal, never a crash someone "fixes" by skipping the check. The connection is
   always closed (`finally`).

### 4.4 `_handle`

After `decide()` allows, and **before any byte of the request is sent upstream**:

```
cid = container_target(path)
if cid:
    doc, reason = lookup_target(upstream_path, cid)
    ok, reason = is_mutator_shaped(doc, cid) if doc is not None else (False, reason)
    if not ok:
        print("DENY %s %s (%s)" % (method, path, reason), file=sys.stderr)
        _refuse(conn, reason); return
print("ALLOW %s %s (%s)" ...)          # moved: ALLOW now always means "forwarded"
```

`decide()` stays pure and unchanged in shape. Today's `ALLOW`/`DENY` print after `decide()`
splits: `DENY` from `decide()` prints where it does now; `ALLOW` prints only after the target
check passes. Create is not id-scoped, so its `ALLOW` line is unchanged, and the bind-agreement
regexes keep their meaning. Everything after the forward — relay, chunked relay, the F18
101-only upgrade — is untouched.

### 4.5 Properties

1. **Per request, not per connection.** On one kept-alive connection a mutator inspect then a
   gateway inspect: the second is refused (trap #1 in the proxy header is exactly the
   first-request-only mistake).
2. **Nothing reaches dockerd before the check.** An attach at the gateway is never answered 101,
   so never enters pass-through.
3. **The inspect result never leaks.** Not relayed, not logged, not retained past the check.
4. **The client cannot steer the lookup.** The id fullmatched `[0-9a-f]{64}`; the path is
   unversioned; no client header is copied.
5. **No check-then-swap.** A full id names one container; `Config.Image`/`Config.Entrypoint`
   cannot change after create. The only race — the target is removed between check and forward —
   gets dockerd's 404, relayed. No bypass.
6. **No shared state.** Each lookup is on its request's thread with its own connection;
   `ThreadingUnixStreamServer` needs no locks.

## 5. Tests

Every new check is seen failing against today's code first (RED). Non-receipt is asserted
**first** and race-free (`_poll_never_received`). Firing controls run in memory or on scratch
copies — **never by editing a tracked file**. Socket classes run 30× in a loop.

**Pure (`bin/docker-create-proxy.test.py`)**
- `decide()`: each of the five id-scoped entries allowed with a 64-hex id; refused with a name
  (`hermes-agent-ads-mutator-run-1a2b`), a 12-char prefix, uppercase hex, 63 and 65 chars, a
  trailing `/`. Unchanged: `GET /containers/json`, `GET /images/hermes-agent-claude/json`.
- `container_target`: returns the id for **every `ALLOWED` entry built on `_CID`**, tested by
  iterating `ALLOWED` itself (a future id-scoped entry cannot skip the check); `None` for the
  list, create, `_ping`, `version`, images.
- `is_mutator_shaped` over **synthetic** docs (never captured from a real gateway): mutator-shaped
  → allowed; refused for gateway-shaped (same image, different entrypoint), auth-init-shaped,
  `Entrypoint` as a string, `Entrypoint: null`, `Config` missing / not a dict, `Id` mismatch,
  image mismatch, non-dict doc.

**Socket — a keep-alive, table-driven fake upstream** (the `TestAttachPassThrough` pattern). It
answers `GET /containers/<id>/json` from a table — mutator id → mutator doc; gateway id →
gateway doc with `Env: ["SECRET=F19-SENTINEL"]`; configurable 404 / 500 / no answer / oversize /
bad JSON — and records every received request per connection. **Because the proxy's lookup and a
client inspect share a path**, the fake classifies each received request by the lookup's
`User-Agent`; "never reached upstream" means no request **without** that User-Agent names the
target id, and client requests in tests use the `/v1.55` prefix as well.
1. Gateway id × {inspect, start, wait, attach, `DELETE …?force=1`}: non-receipt first, then the
   403; the attach case also asserts no `UPGRADE` line.
2. Mutator id × the same five: forwarded; the attach answered 101 still upgrades.
3. Keep-alive: mutator inspect then gateway inspect on one connection → first forwarded, second
   refused and never received.
4. Lookup answered 404 / 500 / never (shortened `LOOKUP_TIMEOUT`) / oversize / bad JSON → refused,
   nothing forwarded.
5. `F19-SENTINEL` never appears in the client's received bytes or on stderr.

**Migration of existing tests.** `TestPlumbing` and `TestAttachPassThrough` use short ids and
fakes that do not answer lookups; they move to 64-hex ids and the table-driven fake. Their
assertions do not change.

**Firing controls** (each must turn at least one test red): remove the target check; make
`container_target` return `None`; loosen `is_mutator_shaped` to image-only (the shared-image
fact); print `ALLOW` before the check; check only the first request per connection.

**Linux CI — `deploy/bind-agreement-integration.test.py`** (job `Bind agreement (root, Linux, real
proxy)`, a required check; **not renamed**)
- The existing broker-path test must still pass: `ALLOW POST …/containers/create` **and**
  `UPGRADE POST …/attach… (101)`. That proves real Compose inspect/attach/start/wait pass the target
  check against real dockerd.
- **New test:** root starts a decoy from `hermes-agent-claude` (the stand-in, `python:3.12-slim`, which has
  `sleep`) with a different entrypoint (`sleep`) and `-e F19_DECOY=F19-SENTINEL`. As `hermes-broker`, through the unit
  proxy's socket: inspect of the decoy's full id → 403 and no sentinel in the response; `DELETE
  …?force=1` → 403 and the decoy is still running afterwards. The decoy is removed in teardown.
- Expected: `bind-agreement: executed 7, skipped 0`; `layout-integration: executed 30, skipped 0`;
  read on the PR **and** the merge commit.

## 6. Box rollout (operator-run)

No unit file changes; the proxy runs from the repo. Exact commands, each with its expected
output, go in the rollout step; the shape is:

1. **Before pulling — see the gap with our own instrument.** As `hermes-broker`, through
   `/run/hermes/docker-proxy.sock`, inspect the gateway's full id, printing **only the HTTP status**
   (`curl -s -o /dev/null -w '%{http_code}'`). Expected **`200`** — today's gap. Never print the
   body.
2. Pull, `sudo systemctl restart hermes-docker-proxy` only (the broker `Requires=` it).
   `is-active` both; `NRestarts=0`.
3. The same command → expected **`403`**, and a `DENY GET … (target is not an ads-mutator run:
   entrypoint mismatch)` line in the proxy journal.
4. BRING-UP Phase 6: `rc=2`, `mutation is disabled`, `ALLOW POST …/containers/create`,
   `UPGRADE POST …/attach… (101)`, and **no** `target` DENY for the mutator's own calls.
5. Kill switch still absent (`sudo test`).

A `target` refusal of the mutator's own calls in step 4 is a finding to understand before
changing anything — **never** widen the check to make it pass.

## 7. Records

- **Findings record:** F19 → fixed (PR #n), assessment result, the 64-hex measurement, the list
  residual, CI run ids and the box `200 → 403` measurement — filled only from real runs. Open
  items updated.
- **BRING-UP:** the kill-switch gate list drops F19, leaving §6 part B (audit-log truncation);
  a rollout note.
- **Proxy header docstring:** the allow-list section notes that container-scoped entries require
  a 64-hex id and pass the target check.
- **Brain:** a candidate decision entry, unpromoted.

## 8. Accepted residuals

- **`GET /containers/json` still enumerates every container** — names, ids, labels (including
  host paths to the compose file), image, command, state, mount paths; **not environment**. With
  this fix, knowing the gateway's id opens nothing. Hiding it needs response rewriting of a
  chunked body on a kept-alive connection — the F18 bug class — and would alter what Compose sees.
- **An allowed inspect returns a mutator's own data**: `HERMES_GOVERNANCE_ROOT` and the
  `--client`/`--changeset`/`--request` arguments, which the broker itself built.
- **A slow dockerd (> 5 s per lookup) refuses rather than hangs.** The wrapper reports a failed
  Compose run as `failed_unverified_exit` (F14), which is the correct direction for a gate.
- **`DELETE` of a container that is already gone** gets a proxy 403, not dockerd's 404. Manual
  cleanup is root's `docker rm -f` anyway.
- **Query strings on id-scoped calls stay uninspected** (`force=1`, `logs=1`): harmless once the
  target must be a mutator run.

## 9. Out of scope

§6 part B (audit-log truncation); filtering the list response; the deferred minors recorded in the
post-F18 handoff (`SHUT_WR`, 1xx responses, duplicate `Host`, etc.).

## 10. Order of work

1. `_CID` and the grammar change + pure `decide()` tests (RED first).
2. `container_target` + `is_mutator_shaped` + pure tests.
3. `lookup_target` + its failure-mode tests against a fake unix-socket server.
4. `_handle` wiring (check before forward; `ALLOW` moved) + the table-driven keep-alive fake,
   the socket tests, and the migration of `TestPlumbing` / `TestAttachPassThrough`.
5. Firing controls; socket classes 30×.
6. Linux CI decoy test.
7. Push, PR, CI counts on the PR.
8. Records (findings, BRING-UP, header docstring); merge; merge-commit CI counts.
9. Box rollout (§6), then a small docs PR recording the box result.
