# The app MCP server answers while a call waits: Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A chat-triggered audit's result reaches Hermes. Today every real audit's reply is lost.

**What happened (first box run, 2026-10-02):** the operator asked Hermes for an audit. The broker queued it, the
runner finished it in about 233 s (`run ok` in `results/`), and Hermes reported "MCP call timed out" at 360 s.
A `list` call right after answered in 4 s.

**Cause:** Hermes's MCP client (`/opt/hermes/tools/mcp_tool.py` in the pinned image) sends a liveness `ping` to
every server on a cadence (`keepalive_interval`, default 180 s) and gives it 30 s; an unanswered ping "is a real
liveness failure" and it reconnects, which discards the in-flight call. `bin/hermes-app-mcp.py` answers one line
at a time: while a `run` call waits for the broker's result (up to 300 s) it does not read stdin, so the ping
goes unanswered and the reply written afterwards has no one to read it.

**Architecture:** `hermes-app-mcp.py` keeps its read loop free. A `tools/call` for `run` or `list` (the two
that wait on the broker) is served on its own thread; everything else, above all `ping`, is answered inline at
once. One lock serialises writes to stdout so replies never interleave. At most `MAX_WAITING` calls wait at a
time; a further one is refused immediately, never queued. The server stays "deliberately dumb": no policy, no
credential, no network; the broker still decides everything.

**Tech Stack:** Python 3 stdlib only (`threading`).

**Spec:** `docs/superpowers/specs/2026-09-30-hermes-chat-triggered-audits-design.md` §3 (request flow), §3.1
(the MCP server), §12 (upstream research: MCP stdio servers).

## Global Constraints

- Python stdlib only; tests are `bin/<name>.test.py`. `infra/hermes-agent/bin/run-bin-tests.sh` must end
  `N/N suites passed`.
- The MCP server holds no credential, does no network I/O and makes no policy decision. A refusal is a normal
  (non-error) tool result. None of that changes.
- No change to `config.yaml.example` (checklist D10.6 pins its `mcp_servers:` block by sha256), to
  `deploy/security-review/CHECKLIST.md`, to the manifest, to the broker or to the runner.
- Every line written to stdout is exactly one complete JSON-RPC message followed by `\n`.
- Test output is pristine (no ResourceWarning, no thread left running after a test).

## Review Focus

1. **A ping during a waiting call.** It must be answered while the call is still waiting, and the call's reply
   must still arrive afterwards on the same connection. Tests: `test_a_ping_is_answered_while_a_run_waits`
   and the real-process test `test_real_process_answers_ping_during_a_run`.
2. **Two replies written at the same moment.** They must not interleave: each stdout line parses as one JSON
   object. Test: `test_concurrent_replies_never_interleave`.
3. **The client hangs up while a call waits.** stdin reaches EOF or stdout is closed: the process must exit
   without a traceback, and the request already filed stays filed (the broker owns it). Test:
   `test_eof_while_a_call_waits_exits_cleanly`.
4. **A flood of waiting calls.** More than `MAX_WAITING` at once: the extra one gets an immediate tool error
   and files no request; the waiting ones are unaffected. Test: `test_more_than_the_cap_is_refused_at_once`.
5. **Order of the quick replies.** `initialize`, `tools/list`, `ping`, `status` and errors are still answered
   inline, in the order received. Test: `test_inline_messages_keep_their_order`.

---

## File Structure

| File | Status | Responsibility |
|---|---|---|
| `infra/hermes-agent/bin/hermes-app-mcp.py` | modify | `MAX_WAITING`, `_waits(server, msg)`, `serve(server, lines, write, max_waiting)`; `main` calls `serve` |
| `infra/hermes-agent/bin/hermes-app-mcp.test.py` | modify | new `Concurrency` tests; the existing `StdioLoop` tests keep passing |
| `infra/hermes-agent/skills/ads-audits/SKILL.md` | modify | what to do when the tool call itself errors or times out |
| `infra/hermes-agent/deploy/BRING-UP.md` | modify | three runbook gaps found on the first box rollout |

---

### Task 1: `hermes-app-mcp.py` serves waiting calls on threads

**Files:**
- Modify: `infra/hermes-agent/bin/hermes-app-mcp.py`
- Test: `infra/hermes-agent/bin/hermes-app-mcp.test.py`

**Interfaces:**
- Consumes: `Server.handle`, `serve_line(server, line)`, `Server.by_tool`, `Server._text`.
- Produces:
  - `MAX_WAITING = 8`;
  - `_waits(server, msg) -> bool`: True for a `tools/call` with an id whose tool maps to op `run` or `list`;
  - `serve(server, lines, write, max_waiting=MAX_WAITING) -> None`: `lines` is any iterable of input lines,
    `write(text)` writes one already-terminated line and flushes;
  - `main` builds the `Server` and calls `serve(s, sys.stdin, write)`.

- [ ] **Step 1: Write the failing tests** (append a `Concurrency` class to `hermes-app-mcp.test.py`)

  Use a real `M.Server(MAN, spool, poll=0.05)` with the real clock and sleep, real threads, and a helper that
  feeds `serve` from a `queue.Queue` (an iterator that blocks on `get()` and stops on a sentinel) and collects
  written lines in a list guarded by a `threading.Condition`, with a `wait_for(predicate, timeout=5)` helper.
  Run `serve` in a thread the test joins in `addCleanup`. Results are produced by writing
  `results/<request_id>.json` into the temp spool, the request id being read from the one file in `requests/`.

  - `test_a_ping_is_answered_while_a_run_waits`: send `tools/call ads_audit_run` (id 1), wait until one file
    is in `requests/`, send `ping` (id 2). Assert the reply with id 2 arrives while no reply with id 1 exists.
    Then write the result file; assert the id 1 reply arrives and its tool text holds that result.
  - `test_inline_messages_keep_their_order`: send `initialize` (1), `tools/list` (2), `ping` (3),
    `tools/call ads_audit_status` with a well-formed id (4), an unknown method (5). Assert replies arrive with
    ids `[1, 2, 3, 4, 5]` in that order.
  - `test_concurrent_replies_never_interleave`: with `max_waiting=8`, start 6 `ads_audit_list` calls for
    different valid slugs; when 6 requests are filed, write all 6 result files; assert 6 replies arrive, every
    written line ends with `\n`, contains exactly one newline, and `json.loads` of each succeeds.
  - `test_more_than_the_cap_is_refused_at_once`: `max_waiting=1`; send a `run` call (id 1), wait for its
    request file, send a second `run` call (id 2). Assert the id 2 reply arrives at once with `isError` true,
    that `requests/` still holds exactly one file, and that after the result file is written the id 1 reply
    arrives.
  - `test_eof_while_a_call_waits_exits_cleanly`: send a `run` call, wait for its request file, send the
    sentinel (EOF). Assert `serve` returns within 2 s, nothing was written to `sys.stderr` (capture it), and
    the request file is still there.
  - `test_a_write_error_does_not_raise`: `write` raises `BrokenPipeError`; send `ping`; `serve` must not
    raise and must keep reading (send EOF, assert it returns).
  - `test_real_process_answers_ping_during_a_run` (the proof of the box failure): start
    `python3 hermes-app-mcp.py --app ads-audit --manifest-dir <repo registry/apps> --spool-root <tmp>` with
    `subprocess.Popen(stdin=PIPE, stdout=PIPE, text=True, bufsize=1)` over a temp spool laid out as
    `<tmp>/ads-audit/{requests,results}`. Write the `run` call line, wait for the request file, write a
    `ping` line, and read one line from stdout with a 5 s deadline (read in a helper thread): it must be the
    ping reply. Then write the result file and read the next line: the `run` reply. Close stdin; the process
    must exit 0 within 5 s. Kill it in `addCleanup` if it is still alive.

- [ ] **Step 2: Run to verify they fail**

Run: `python3 infra/hermes-agent/bin/hermes-app-mcp.test.py Concurrency -v`
Expected: FAIL. `AttributeError: … has no attribute 'serve'` for the in-process tests; the real-process test
times out waiting for the ping reply (that timeout IS the box defect).

- [ ] **Step 3: Implement** (in `hermes-app-mcp.py`)

   Add `threading` to the imports. After `serve_line`:

```python
MAX_WAITING = 8     # run/list calls waiting on the broker at once; one more is refused, never queued


def _waits(server, msg):
    """True for a tools/call that waits on the broker's result (run, list): minutes, not milliseconds."""
    if not isinstance(msg, dict) or msg.get("method") != "tools/call" or msg.get("id") is None:
        return False
    p = msg.get("params")
    name = p.get("name") if isinstance(p, dict) else None
    return isinstance(name, str) and server.by_tool.get(name) in ("run", "list")


def serve(server, lines, write, max_waiting=MAX_WAITING):
    """Answer every input line. A run or list call waits for the broker's result, so it gets its
    own thread and this loop keeps reading: the client's liveness ping must be answered WHILE a
    call waits. Hermes pings each MCP server on a cadence (default 180 s), allows 30 s, and
    reconnects on silence, which discarded the reply of every audit that outlasted a ping
    (first box run, 2026-10-02: the audit finished `ok` in 233 s, Hermes saw a 360 s timeout).
    One lock keeps replies whole; a reply nobody can read any more is dropped, never raised."""
    lock = threading.Lock()
    slots = threading.BoundedSemaphore(max_waiting)

    def emit(out):
        if out is None:
            return
        try:
            with lock:
                write(json.dumps(out) + "\n")
        except (OSError, ValueError):             # the client hung up (closed pipe / closed file)
            pass

    def waited(line):
        try:
            emit(serve_line(server, line))
        finally:
            slots.release()

    for line in lines:
        try:
            msg = json.loads(line)
        except ValueError:
            msg = None
        if _waits(server, msg):
            if slots.acquire(blocking=False):
                threading.Thread(target=waited, args=(line,), daemon=True).start()
            else:
                emit({"jsonrpc": "2.0", "id": msg["id"],
                      "result": server._text({"error": "too many requests are waiting; try again later"},
                                             error=True)})
            continue
        emit(serve_line(server, line))
```

   Replace the loop in `main`:

```python
    def write(text):
        sys.stdout.write(text); sys.stdout.flush()
    serve(s, sys.stdin, write)
```

   Notes for the implementer:
   - The waiting threads are daemons: when stdin reaches EOF `serve` returns, `main` returns, and the process
     exits without joining them. A request already filed stays with the broker.
   - `serve_line` re-parses the line; that is deliberate (one code path decides what a message is).
   - If a daemon thread can print a traceback at interpreter shutdown in the real-process test, fix it in
     `emit`/`waited` (catch what is actually raised), not by silencing stderr.

- [ ] **Step 4: Run to verify they pass**

Run: `python3 infra/hermes-agent/bin/hermes-app-mcp.test.py -v`
Expected: all PASS, output pristine, the run takes a few seconds at most.

Run: `infra/hermes-agent/bin/run-bin-tests.sh`
Expected: ends `53/53 suites passed`.

- [ ] **Step 5: Commit**

```bash
git add infra/hermes-agent/bin/hermes-app-mcp.py infra/hermes-agent/bin/hermes-app-mcp.test.py
git commit -m "fix(hermes): app MCP server answers pings while a call waits (chat audit replies were lost)"
```

---

### Task 2: The skill and the runbook, from the first box rollout

**Files:**
- Modify: `infra/hermes-agent/skills/ads-audits/SKILL.md`
- Modify: `infra/hermes-agent/deploy/BRING-UP.md`

No test cycle; `python3 infra/hermes-agent/bin/security-review-checklist.test.py` and
`infra/hermes-agent/bin/run-bin-tests.sh` must still pass.

- [ ] **Step 1: `SKILL.md`.** On the box, when the tool call timed out, Hermes told the operator to run
  `sudo run-client-audit <client>`. The audit had in fact succeeded, so that advice would have paid for a
  second one. Add one row to the "Reporting a result" table, after `pending`:

```markdown
| the tool call itself errors or times out (no `status` came back) | you got no answer; the audit may still be running or may have finished | do NOT call `ads_audit_run` again and do NOT suggest the manual command (it would start a second audit). Call `ads_audit_list` once and report the latest timestamp; the operator can read it with `sudo show-audit <client>` |
```

  and one line to "Never": `- Treat a tool error or timeout as a failed audit.`

- [ ] **Step 2: `BRING-UP.md`, part 1 step 5.** The step expects `absent` because the retired
  `claude-auth-init` sidecar used to clear the file on a recreate with no key. When all three parts are pulled
  at once, the sidecar is already gone and the file stays. After the `→ absent` line, add:

```markdown
   `STILL-PRESENT` after pulling all three parts at once is expected (the retired sidecar that cleared the
   file no longer exists). The file holds the Anthropic key: check it is the old one
   (`sudo stat -c '%y' /opt/hermes-agent/data/home/.claude/settings.json` → a date before today), then
   `sudo shred -u /opt/hermes-agent/data/home/.claude/settings.json` and re-run the test → `absent`.
   A file dated today means something still writes it: stop.
```

- [ ] **Step 3: `BRING-UP.md`, part 2 step 10.** `docker compose` only finds its file from
  `/opt/hermes-agent`, and the journal needs root. Change the two commands to
  `cd /opt/hermes-agent && sudo docker compose exec -it hermes-agent hermes chat` and
  `sudo journalctl -u hermes-app-broker@ads-audit -n 20 --no-pager`, and add after the `Expect` sentence:
  `A reply of "MCP call timed out" while the journal shows `status=ok` for that request means the gateway is
  running a tool server from before the ping fix: pull, then `sudo docker compose restart hermes-agent`.`

- [ ] **Step 4: `BRING-UP.md`, part 2 step 7.** Add one line at the end of the step:
  `After any later pull that changes `bin/hermes-app-mcp.py`: `cd /opt/hermes-agent && sudo docker compose restart hermes-agent` (the gateway keeps the old tool server running until then).`

- [ ] **Step 5: Run the suites and commit**

Run: `infra/hermes-agent/bin/run-bin-tests.sh && python3 infra/hermes-agent/bin/security-review-checklist.test.py && python3 infra/hermes-agent/bin/check-checklist-version.py --base origin/main`
Expected: `53/53 suites passed`, `OK`, `unchanged (version 1.12)`.

```bash
git add infra/hermes-agent/skills/ads-audits/SKILL.md infra/hermes-agent/deploy/BRING-UP.md
git commit -m "docs(hermes): ads-audits skill handles a tool timeout; BRING-UP gaps from the first box rollout"
```

---

## Self-review notes (done while writing)

- **Coverage:** the lost reply is Task 1; each Review Focus line has its test there. The skill and runbook
  gaps the same rollout exposed are Task 2.
- **Why not a config change:** raising `keepalive_interval` in `config.yaml` would only move the failure to
  longer audits, and that block is pinned by checklist D10.6 (a change means a version bump).
- **What this does not change:** Hermes's 360 s tool timeout and the server's 300 s wait. An audit longer than
  300 s still returns `pending` with its `request_id`, as designed.
- **Not verified here:** that the pinned Hermes client pings stdio servers during an in-flight call is
  inferred from its source (`_keepalive_probe`, default cadence 180 s, 30 s allowance, reconnect on failure)
  and from the box symptom. The proof is the next chat audit on the box after this is pulled.
- **Fingerprint:** `bin/` and `deploy/` are in the box fingerprint; this must be pulled before review #6's
  evidence is collected.
