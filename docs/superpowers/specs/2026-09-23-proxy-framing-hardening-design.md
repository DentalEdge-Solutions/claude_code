# Proxy framing hardening + `UMask=0077` (design)

**Status:** approved in conversation 2026-09-23, awaiting written-spec review.
**Source:** the 2026-09-17 handoff `docs/superpowers/handoffs/2026-09-17-vps-deploy-and-remeasurement.md`
§6 (first bullet), and §7 of `docs/evaluations/2026-09-17-f3-framing-disagreement-measurement-plan.md`.
**Scope:** part **A** of the §6 gate — request-framing hardening in `docker-create-proxy.py` plus
`UMask=0077` on both units. Part **B** (audit-log truncation: append-only or a host-side writer)
is its own cycle.
**Naming:** "F3" in the Phase B design / measurement plan is this framing question. It is NOT the
bring-up findings record's F3 (usable sudo). This document says "the framing hardening".

**Mutation stays disabled throughout. The kill switch is ABSENT and nothing here creates it.**
**The proxy allow-list is not widened.**

## 1. Problem

`docker-create-proxy.py` decides each request from its request line, headers and body, then
forwards **the original header block verbatim** to dockerd (`_handle`, `up.sendall(head +
b"\r\n\r\n" + body)`). Its safety rests on an invariant: **the proxy and dockerd always agree
where a request ends.** `341ed1e` (CL.TE) and `65df9b1` (Content-Length as `1*DIGIT`) closed three
breaks. Headers are still recognised by prefix (`lo.startswith(b"content-length:")`,
`lo.startswith(b"transfer-encoding:")`) over a split on `\r\n`, which leaves four forms where the
proxy may not see a framing header dockerd honours:

| # | Form | What the proxy does today | Status |
|---|---|---|---|
| 1 | `X-Pad: pad\r\n\tTransfer-Encoding: chunked` (obs-fold) | no `Transfer-Encoding` seen; forwarded | bytes reach upstream — measured 2026-09-17 (darwin) |
| 2 | `Transfer-Encoding : chunked` (space before colon) | same | measured 2026-09-17 |
| 3 | `Content-Length: 5` + `Content-Length: 77` | keeps the **last**; forwards both | measured 2026-09-17 |
| 4 | a bare `\n` inside a header line, e.g. `X-Pad: a\nTransfer-Encoding: chunked`; likewise a bare `\n\n` | one harmless header line; the proxy's head ends only at `\r\n\r\n` | **new, inferred, unmeasured** — Go's textproto reader treats a bare `\n` as a line end, so dockerd would see a separate `Transfer-Encoding` line, or end the head earlier than the proxy |

Whether dockerd actually frames any of these as a second request was never measured (§5 of the
measurement plan is unfilled). §6 of that plan decided in advance: **harden either way.**

## 2. Decisions

- **Harden without the VPS measurement** (operator, 2026-09-23). The measurement becomes
  informative, not a prerequisite.
- **Approach A**: one strict, pure parser `_parse_head` enforces a grammar over the whole head
  before anything else runs. Chosen over inline checks in `_handle` (testable only through a
  socket; `_handle` keeps growing) and over re-serialising headers (changes every byte dockerd
  receives; a larger design).
- **Strict choices**: request version exactly `HTTP/1.1`; header values printable ASCII only.
- **`UMask=0077` on both units** (operator, 2026-09-23): `hermes-docker-proxy.service` (named by
  the handoff) and `hermes-broker.service` (F12 made approvals and records umask-independent for
  exactly this; spool files are written `0640` on the fd — `spool_lib.SPOOL_FILE_MODE`; `seen/` is
  broker-private `0700`).

## 3. Design

### 3.1 `_parse_head(head) -> (method, path, content_length)` — `bin/docker-create-proxy.py`

Pure function over `head` (the bytes before the first `\r\n\r\n`, as `_read_until_headers`
returns them). On any violation it raises `HeadRefused(reason)`; `reason` is one of a fixed set
of strings and **never contains request bytes**.

1. **Line structure.** `lines = head.split(b"\r\n")`. If any element contains `\r`, `\n` or
   `\x00` → `"malformed request"`. (Form 4.)
2. **Request line** `lines[0]`: exactly three parts separated by single spaces, else
   `"malformed request line"`:
   - method: token `[!#$%&'*+.^_`|~0-9A-Za-z-]+`;
   - target: printable ASCII only, `[\x21-\x7e]+`;
   - version: exactly `HTTP/1.1`.
3. **Each header line** `lines[1:]`: `name ":" value`, else `"malformed header line"`:
   - name: a token that starts the line and is immediately followed by `:` (forms 1 and 2 fail
     here — a line starting with SP/HTAB, or a space before the colon, is not a token);
   - value: after stripping SP/HTAB on both sides, only `\t` and `[\x20-\x7e]`.
4. **Framing headers**, names compared case-insensitively and exactly:
   - `Transfer-Encoding` present at all → `"Transfer-Encoding is not permitted on requests"`
     (unchanged reason; now exact-name, not prefix);
   - a second `Content-Length` → `"duplicate Content-Length"`, even with an identical value
     (form 3);
   - `Content-Length` not `1*DIGIT` → `"malformed Content-Length"` (unchanged reason);
   - absent → `content_length = 0` (unchanged).
5. `HeadRefused` is a new `ValueError` subclass carrying `.reason`, defined next to `_parse_head`.
   The existing comments explaining CL.TE (`341ed1e`) and the digits-only rule (`65df9b1`) move
   with the logic into `_parse_head`.

### 3.2 `_handle`

- Per request: `head, rest = _read_until_headers(conn, buf)` (unchanged) →
  `method, path, clen = _parse_head(head)`.
- On `HeadRefused as e`: `_refuse(conn, e.reason)`, log, **return** (close the connection — after
  an unparseable head there is no safe place to resume reading).
- Log line: `DENY <method> <path> (<reason>)` when the request line parsed (method and path have
  passed the grammar); `DENY - - (<reason>)` when it did not. Refused bytes never reach the journal.
- Removed from `_handle`: the per-header loop and the `has_te` / `bad_clen` branches. Everything
  after — the uninspectable-create check, `MAX_BODY`, body read, `decide()`, the verbatim forward,
  the response relay — is unchanged.

### 3.3 Units — `deploy/hermes-docker-proxy.service`, `deploy/hermes-broker.service`

- Add `UMask=0077` to the `[Service]` section of both.
- `serve()` code is unchanged. Beside `os.chmod(listen, 0o660)` a comment states: under
  `UMask=0077` the socket is created `0600`; this `chmod` opens it to `hermes-rail`; containment
  no longer depends only on `RuntimeDirectoryMode=0750`.

## 4. Tests

Every new refusal assertion pins the **reason string** (a refusal for an unrelated reason must not
satisfy it). Every new check is seen failing first. Controls never edit a tracked file.

**`bin/docker-create-proxy.test.py` — new `TestParseHead` (pure, no sockets)**
- Accepts, returning the right `(method, path, content_length)`: `GET /_ping`; `POST
  /v1.55/containers/create?name=x` with `Host`, `User-Agent`, `Content-Type`,
  `Content-Length`; `POST .../wait?condition=removed` with `Content-Length: 0`; `POST .../attach`
  with `Connection: Upgrade` and `Upgrade: tcp`; a head with no headers.
- Refuses, one test per rule, each asserting its reason:
  - bare `\n`, bare `\r`, `\x00` → `malformed request`;
  - 2 parts, 4 parts, double space, `HTTP/1.0`, control char in target → `malformed request line`;
  - leading SP, leading HTAB, `Name : v`, empty name, control char in value, byte `0x80` in value
    → `malformed header line`;
  - two `Content-Length` (different, and identical) → `duplicate Content-Length`;
  - `7_7`, `-5`, empty → `malformed Content-Length`;
  - `transfer-encoding: chunked`, `TRANSFER-ENCODING: gzip` → `Transfer-Encoding is not
    permitted on requests`.

**`bin/docker-create-proxy.test.py` — `TestPlumbing` (real `_handle`, fake upstream)**
- For each of forms 1–4: an allowed `POST .../wait` carrying a smuggled `POST /containers/create`
  (privileged, `/:/host` bind) in its tail. Assert a `403` with the expected reason, and that
  `/containers/create` appears **nowhere in `upstream_raw`** (the full received bytes, not the
  first line). Run against the current code first: forms 1–3 must fail (measured to reach the
  upstream); form 4's pre-fix result is recorded either way.
- The existing positive control and all 40 existing proxy tests pass unchanged.

**`deploy/units.test.py`**
- Both units carry `UMask=0077`. Control: the same parser on an in-memory copy with the line
  removed fails.

**Linux CI** — `Bind agreement (root, Linux, real proxy)` unchanged: the real Compose client
through the real proxy must still `ALLOW POST .../containers/create`; `executed 6, skipped 0`;
`layout-integration: executed 30, skipped 0`. Read on the PR and on the merge commit. CI starts
the proxy directly, not under systemd, so it does **not** exercise `UMask` — the box does (§5).

## 5. Box rollout (operator-run; a BRING-UP block)

The unit files are **copied** to `/etc/systemd/system/` (`README.md:1201-1203`), so a pull alone
does not apply `UMask`.

```bash
sudo git -C /opt/projects/claude_code pull --ff-only
sudo cp /opt/projects/claude_code/infra/hermes-agent/deploy/hermes-docker-proxy.service /etc/systemd/system/
sudo cp /opt/projects/claude_code/infra/hermes-agent/deploy/hermes-broker.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl restart hermes-docker-proxy     # the broker Requires= it, so it restarts too
sudo systemctl restart hermes-broker
systemctl show -p UMask hermes-docker-proxy hermes-broker          # UMask=0077, both
stat -c '%U:%G %a %n' /run/hermes/docker-proxy.sock                # hermes-docker-proxy:hermes-rail 660
systemctl is-active hermes-docker-proxy hermes-broker              # active, active
systemctl show -p NRestarts hermes-docker-proxy hermes-broker      # not climbing
```

Then re-run BRING-UP Phase 6's pasted create: expect `rc=2`, `mutation is disabled`, and `ALLOW
POST /v…/containers/create` in `journalctl -u hermes-docker-proxy`. That is the box's end-to-end
positive control for the stricter parser, and it discharges the end-to-end check the 2026-09-17
handoff §5 / measurement plan §8 still owe for `65df9b1`.

**If a real request is refused** (`malformed …` in the proxy journal): that is the finding.
Identify which client sent what before touching the grammar; never loosen a rule to make the rail
pass.

## 6. Records

- **Measurement plan** §7: "Applied (PR #n) without the §5 measurement, per §6"; form 4 added to
  §1's table as inferred; §5 stays blank and is now informative.
- **Findings record** `2026-09-21-vps-first-bring-up-findings.md`, the "Still open: the §6
  hardening gates, including `UMask=0077` …" line → the framing hardening and `UMask` done (PR
  #n); open: audit-log truncation.
- **BRING-UP**: the rehearsal-gate line "Still required before the kill switch can be created: the
  §6 hardening gates" → "audit-log truncation (§6 B)"; plus the §5 rollout block.
- **Brain**: a candidate decision entry, left for the operator's promote.
- PR number and CI run ids are filled only from real runs.

## 7. Out of scope

- **B — audit-log truncation**: its own cycle.
- Response-side parsing (dockerd is the trusted upstream).
- Re-serialising headers (approach C).
- Running the §5 framing measurement.

## 8. Accepted risks

- **A legitimate request the grammar refuses** (e.g. a non-ASCII `User-Agent`, `HTTP/1.0`). Fails
  closed: nothing mutates, the refusal is logged with its reason; Linux CI and the box's Phase 6
  run are placed to surface it. Investigate before loosening.
- **`UMask=0077` on the broker is proven only on the box**, by the §5 checks; the broker's own
  shared files set explicit modes (F12, spool).

## 9. Order of work

1. `_parse_head` + `HeadRefused` + `TestParseHead` (§3.1).
2. `_handle` uses it; the four smuggling tests in `TestPlumbing` (§3.2).
3. `UMask=0077` in both units + `units.test.py`; the `serve()` comment (§3.3).
4. Push, PR, CI counts.
5. Records + BRING-UP rollout block (§5, §6); merge-commit CI.
