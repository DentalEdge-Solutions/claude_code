# F18 — The proxy's attach pass-through (design)

**Status:** approved 2026-09-23; implemented in PR #50.
**Finding:** F18 in `docs/superpowers/specs/2026-09-21-vps-first-bring-up-findings.md` (found by the
whole-branch review of PR #48). **Gates the kill switch.**
**Scope:** narrow — only when the proxy switches a connection to raw pass-through. The separate
"attach may target any container" gap is recorded here as **F19** and fixed in its own cycle
(operator decision, 2026-09-23).

**Mutation stays disabled throughout. The kill switch is ABSENT and nothing here creates it.**
**The proxy allow-list's contents are not changed.**

## 1. Problem

`infra/hermes-agent/bin/docker-create-proxy.py`, `_handle`: after `decide()` allows a request and
it is forwarded, `if "/attach" in path:` (`:497`) switches the connection to raw two-way pumping
and returns. Nothing after that point passes `_parse_head` or `decide()`. The test is a substring
over the **whole target, query string included**, and it runs **before** dockerd has answered.
Three routes, each measured on a scratch copy with a keep-alive fake upstream (not a real
dockerd):

| # | Route | Why it pumps |
|---|---|---|
| a | `GET /_ping?x=/attach`, then anything | `/attach` appears in the query string |
| b | `DELETE /v1.55/containers/attach` (and other allowed paths whose id is literally `attach`), then anything | `_ID` accepts `attach` |
| c | a real `POST /containers/<id>/attach` that dockerd answers with an error (e.g. 404), then anything | pumping starts before the answer; dockerd keeps the connection and parses the next bytes as a fresh request |

After any of them a privileged `POST /containers/create` reached the upstream with no `ALLOW`/`DENY`
logged. Separately, client bytes already read past the attach request (`buf`) are dropped when
pumping starts.

**What is known about real attach traffic.** Compose opens a separate connection each for
`attach`, `start` and `wait` (Task 1 measurement, `docker-create-proxy.py:66-72`). The Docker
client sends `Connection: Upgrade` / `Upgrade: tcp` on attach, and dockerd is expected to answer
`101 UPGRADED` — **inferred from Docker's client/daemon behaviour, never measured in this repo**
(the 2026-09-16 measurement records only that attach "was detected and degraded to raw relay").

## 2. Decisions

- **Narrow scope; F19 separate** (operator).
- **Approach A** (operator): pass-through only for a real attach that dockerd upgrades; **any other
  answer to an attach is relayed and the connection is closed.** Chosen over "relay and keep
  inspecting" (one more state, and it carries `buf`/loop state across an attach — the area F18
  and the smuggling bugs lived in) and over pinning attach targets (F19's problem).

## 3. Design — `bin/docker-create-proxy.py`

### 3.1 One definition of attach

- `_ATTACH_RE = re.compile(_V + r"/containers/" + _ID + r"/attach")`, defined before `ALLOWED`.
  The `ALLOWED` attach entry uses it: `("POST", _ATTACH_RE)`.
- `_is_attach(method, path)` → `method == "POST" and bool(_ATTACH_RE.fullmatch(_path_only(path) or ""))`.
  The query string is stripped, so `GET /_ping?x=/attach` is not an attach; neither is
  `DELETE /containers/attach` (method).
- `_status_code(rhead)` → the second space-separated field of the response's first line as an
  `int` when it is exactly three ASCII digits, else `None`.

### 3.2 `_handle`, after `decide()` allows

1. Forward `head + b"\r\n\r\n" + body` (unchanged).
2. **Always** read the response head: `rhead, rrest = _read_until_headers(up, b"")`. The early
   `if "/attach" in path:` block is removed.
3. `attach = _is_attach(method, path)`.
4. **`attach` and `_status_code(rhead) == 101`:** `conn.sendall(rhead + b"\r\n\r\n" + rrest)`; if
   `buf`, `up.sendall(buf)`; log `UPGRADE POST <path> (101)`; pump both directions (the existing
   `pump` pair); return.
5. **`attach` and any other status (including `None`):** relay the response exactly as today (the
   chunked path, or the Content-Length path), log `DENY-FOLLOWUP POST <path> (attach answered
   <status>, not upgraded; connection closed)`, and **return** — close the connection.
6. **Not `attach`:** unchanged — relay and continue the per-connection loop.

`_parse_head`, `decide()`, the allow-list contents, and the relay of non-attach responses are
unchanged. The logged `<path>` has already passed `_parse_head`'s printable-ASCII grammar; the
logged status is an int or `None`, never raw upstream bytes.

## 4. Tests

Every new check is seen failing against today's code first. Non-receipt is asserted **first** and
race-free (`_assert_never_reached_upstream`-style bounded poll). Controls never edit a tracked file.

**Pure (`bin/docker-create-proxy.test.py`)**
- `_is_attach`: true for `POST /v1.55/containers/abc/attach?stream=1&stdout=1`; false for
  `GET /_ping?x=/attach`, `DELETE /v1.55/containers/attach`, `GET /v1.55/containers/attach/json`,
  `POST /v1.55/containers/abc/attachx`.
- `_status_code`: `HTTP/1.1 101 UPGRADED` → 101; `HTTP/1.1 404 Not Found` → 404;
  `HTTP/1.1  101 x`, `HTTP/1.1 1O1 x`, `HTTP/1.1`, `garbage` → `None`.
- The `ALLOWED` attach entry is the same object as `_ATTACH_RE`.

**Socket — new class `TestAttachPassThrough` with a KEEP-ALIVE fake upstream**
The fake keeps each connection open, answers requests in order, records every received byte
raw, and answers an attach per the test: `101` (upgrade headers + initial stream bytes, then
echoes/records what it receives), `404`, `200`, or a garbled status line.
1. `GET /_ping?x=/attach` then a smuggled privileged create → the create never reaches upstream;
   the client gets a `403` for it.
2. `DELETE /v1.55/containers/attach` then the create → same.
3. `POST …/attach` answered `404` then the create → client receives the 404; the connection
   closes; the create never reaches upstream.
4. `POST …/attach` answered `101` → client receives the 101 and the initial stream bytes; bytes
   the client then sends reach the fake; bytes the fake sends reach the client.
5. Attach request + extra bytes in **one** `sendall`, answered `101` → the extra bytes reach the
   fake after the upgrade (today they are dropped).
6. Attach answered `200`, and attach answered with a garbled status → relayed, then closed; a
   request sent afterwards never reaches upstream.

**Linux CI — `deploy/bind-agreement-integration.test.py`** (job `Bind agreement (root, Linux,
real proxy)`, a required check; not renamed)
- The broker-path test additionally asserts the proxy log matches
  `UPGRADE POST /v[0-9.]+/containers/[^ ]+/attach[^ ]* \(101\)`. This **measures** that real
  Compose attach is answered 101 and streams through the new path. Its existing assertions
  (`rc == 2`, `mutation is disabled` — which only arrives through the attach stream — the
  attested `HERMES-EXIT` line, `ALLOW` on create) stay.
- `bind-agreement: executed 6, skipped 0`; `layout-integration: executed 30, skipped 0`; read on
  the PR and on the merge commit.

## 5. Box rollout (operator-run)

No unit file changes. The proxy runs its script from the repo, so:

```bash
sudo git -C /opt/projects/claude_code pull --ff-only
sudo systemctl restart hermes-docker-proxy     # the broker Requires= it and restarts with it
systemctl is-active hermes-docker-proxy hermes-broker
systemctl show -p NRestarts hermes-docker-proxy hermes-broker
```

Then BRING-UP Phase 6: `rc=2`, `mutation is disabled`, `ALLOW POST …/containers/create`, and
**`UPGRADE POST …/attach… (101)`** in `journalctl -u hermes-docker-proxy`. A `DENY-FOLLOWUP`
line for the real attach is a finding — the rail fails closed — to be understood before
changing anything.

## 6. Records

- **Findings record:** F18 → fixed (PR #n), with the CI run id and the `UPGRADE … (101)`
  measurement filled only from real runs. **F19** (new section): the allow-list lets the broker
  attach to **any** container id, including the Hermes gateway (with `stdin=1`, writing its
  input); recorded, not fixed; whether it gates the kill switch is assessed in its own cycle,
  and it is listed as a gate until then. Open-items list updated.
- **BRING-UP:** the kill-switch gate becomes "§6 part B (audit-log truncation) and F19 (to be
  assessed)"; F18 removed; a rollout note for this change.
- **Brain:** a candidate decision entry, unpromoted. PR number and run ids only from real runs.

## 7. Out of scope

F19; `wait`/`start` handling; Ruling 18 (chunked-response relay closes); response-side parsing.

## 8. Accepted risks

- **A Docker version that answers a real attach with `200` instead of `101`**: relayed and
  closed; Compose loses the output; the wrapper reports **4 (unverified)**. Fails closed; CI's new
  `UPGRADE` assertion and the box's journal line surface it.
- **A genuine `101` attach still opens a raw stream to whatever container the id names** — F19.
- **An attach sent WITHOUT `Upgrade: tcp`** is answered by dockerd with a `200` hijack, not a
  `101`; the proxy relays the head and closes (fail-safe — same path as the `200` risk above).
  The Docker CLI and Compose always send `Upgrade: tcp`, and Linux CI measured the `101` path
  (run 35999764190).

## 9. Order of work

1. `_ATTACH_RE`, `_is_attach`, `_status_code` + pure tests.
2. `_handle`: read the response first; upgrade only on attach+101; relay-and-close otherwise;
   forward `buf`; the keep-alive fake upstream and the six socket tests.
3. Linux CI assertion.
4. Push, PR, CI counts.
5. Records (F18 fixed, F19 new, BRING-UP gate + rollout note); merge-commit CI.
