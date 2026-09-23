# F3 — proxy/dockerd framing disagreement: measurement plan

> **Status: PLAN. Not yet run.** Run on the VPS, in the same session as the Phase B
> endpoint re-measurement, and fill in §5 with what was observed.
> **Created 2026-09-17.** Harness self-tested on darwin before travel (§3).

## 1. The question, stated so it can be answered wrong

`docker-create-proxy.py` decides every request by parsing the request line, the headers
and the body, then forwards **the original header block verbatim** to dockerd. Its safety
therefore rests on an unproven invariant:

> **the proxy and dockerd always agree about where a request ends.**

`341ed1e` closed one way that invariant broke — `Transfer-Encoding` forwarded verbatim
while the proxy framed by `Content-Length` (CL.TE smuggling, host root). `65df9b1` closed
two more by parsing `Content-Length` as `1*DIGIT` instead of whatever Python's `int()`
accepts.

Three forms remain where **the proxy does not see a header that dockerd might honour**,
measured 2026-09-17 against the fixed proxy on darwin. In each, the create's bytes reached
the upstream socket:

| # | Request form | Why the proxy misses it |
|---|---|---|
| 1 | `X-Pad: pad\r\n\tTransfer-Encoding: chunked` | obs-fold continuation line; `startswith(b"transfer-encoding:")` is false for a line beginning with a tab |
| 2 | `Transfer-Encoding : chunked` | space before the colon; same prefix test fails |
| 3 | `Content-Length: 5` + `Content-Length: 77` | the parse loop keeps the **last** value |
| 4 | `X-Pad: a\nTransfer-Encoding: chunked` (bare LF) | a split on CRLF sees one header; Go's textproto treats bare LF as a line end — **inferred 2026-09-23, not measured** |

**What was measured is that the bytes arrive. What was NOT measured is whether dockerd
parses them as a second request** — which is the only thing that makes any of them a
bypass. Go's `net/http` is plausibly stricter than Python on all three, in which case each
is fail-closed and this is a hardening nicety. That plausibility is not evidence, and the
C1 Critical was born from exactly this kind of assumption about how the upstream frames.

There is no Go toolchain and no running daemon on the dev machine. **The VPS is the first
place this is answerable.**

## 2. Why this is safe to run, and the one rule

The smuggled request in every case is **`GET /_ping`**. Proving a desync does not require
proving it with a privileged create, and must not be done that way: two responses to one
send is the entire proof.

- **Read-only.** `GET /version` carrier, `GET /_ping` smuggled. Nothing is created,
  started, or written.
- **Runs against dockerd directly, bypassing the proxy**, because the proxy's behaviour is
  already known — it forwards these verbatim. Isolating dockerd's parser is the point.
- **Requires** the kill switch to be ABSENT (mutation disabled at rest) and no mutation
  in flight. This is a bring-up measurement, not something to run beside live work.
- **Never** substitute `/containers/create` for `/_ping` "to be sure". If `/_ping` comes
  back twice, you are already sure.

## 3. The harness, and the proof that it discriminates

Self-tested on darwin 2026-09-17 before travel, because a measurement whose instrument has
never been checked is the failure this project keeps paying for:

```
self-test strict   upstream sent 1 -> harness counted 1  OK
self-test desync   upstream sent 2 -> harness counted 2  OK
HARNESS DISCRIMINATES
```

It was also run end to end against a deliberately strict fake parser (frames by
`Content-Length`, ignores `Transfer-Encoding`, one response per request): controls passed,
all three evasion rows reported 1 response, 0 desyncs — i.e. the harness reports "safe"
correctly when the target really is safe, which is the half of a control that usually goes
unchecked.

**`CONTROL-POS` is load-bearing.** It pipelines two ordinary requests and requires the
harness to see **two** responses. Without it, a "1" on every evasion row could mean the
instrument cannot count past one, and the whole run would prove nothing. If either control
misbehaves, the script says so and every other row is void.

Save as `/tmp/f3-measure.py` on the VPS (not committed: one-off, same as the throwaway
pass-through used for the 2026-09-16 endpoint measurement).

```python
#!/usr/bin/env python3
"""F3: does dockerd parse what this proxy forwards as ONE request, or TWO?

Sends crafted bytes straight at the Docker socket, bypassing the proxy — the proxy's
behaviour is already known (it forwards these verbatim), so the open question is purely
what Go's net/http does with them. TWO responses to one send = dockerd framed a second,
wholly uninspected request = live bypass.

READ-ONLY. The smuggled request is GET /_ping. Proving the desync does not require
proving it with a privileged create, and must not be done that way.

  --self-test   run the harness against local fakes; no Docker needed
"""
import argparse, socket, sys, time

PING = b"GET /_ping HTTP/1.1\r\nHost: d\r\n\r\n"


def send(path, req, timeout=3.0):
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.settimeout(timeout)
    s.connect(path)
    s.sendall(req)
    out = b""
    try:
        while True:
            d = s.recv(65536)
            if not d:
                break
            out += d
    except (socket.timeout, OSError):
        pass
    s.close()
    return out


def count_responses(raw):
    return raw.count(b"HTTP/1.1 ")


def status_lines(raw):
    # Split on the marker itself, NOT on CRLF: a pipelined second response follows the
    # first one's body with no CRLF in front of it, so a CRLF split hides it — and the
    # second response's STATUS is the whole diagnosis here (a 400 means dockerd
    # rejected the request; a 200 means it framed and served a second one).
    out = []
    for part in raw.split(b"HTTP/1.1 ")[1:]:
        out.append("HTTP/1.1 " + part.split(b"\r\n")[0].decode("latin1", "replace"))
    return out


def cases():
    tail = b"0\r\n\r\n" + PING
    n = str(len(tail)).encode()
    base = b"GET /version HTTP/1.1\r\nHost: d\r\n"
    return [
        ("CONTROL-NEG  one ordinary request", PING, 1,
         "harness must see exactly one response to one request"),
        ("CONTROL-POS  two pipelined requests", PING + PING, 2,
         "harness must be ABLE to see two — without this, a '1' below proves nothing"),
        ("OBS-FOLD     TE on a continuation line",
         base + b"X-Pad: pad\r\n\tTransfer-Encoding: chunked\r\nContent-Length: " + n
         + b"\r\n\r\n" + tail, 1, "2 = dockerd honoured the folded TE = LIVE BYPASS"),
        ("TE-SPACE     'Transfer-Encoding : chunked'",
         base + b"Transfer-Encoding : chunked\r\nContent-Length: " + n + b"\r\n\r\n"
         + tail, 1, "2 = dockerd accepted the malformed header name = LIVE BYPASS"),
        ("DUP-CL       Content-Length: 5 then full length",
         base + b"Content-Length: 5\r\nContent-Length: " + n + b"\r\n\r\n" + tail, 1,
         "2 = dockerd framed by the FIRST length = LIVE BYPASS"),
    ]


def run(path):
    print("target: %s\n" % path)
    verdicts = []
    for label, req, expect, meaning in cases():
        raw = send(path, req)
        n = count_responses(raw)
        ok = (n == expect)
        verdicts.append((label, n, expect, ok))
        print("%-46s responses=%d (expected %d) %s"
              % (label, n, expect, "OK" if ok else "<<< INVESTIGATE"))
        for sl in status_lines(raw):
            print("      %s" % sl)
        if not ok:
            print("      MEANING: %s" % meaning)
        print()
        time.sleep(0.2)
    neg = [v for v in verdicts if v[0].startswith("CONTROL-NEG")][0]
    pos = [v for v in verdicts if v[0].startswith("CONTROL-POS")][0]
    if not (neg[3] and pos[3]):
        print("CONTROLS DID NOT BEHAVE — every other row below is meaningless.")
        return 2
    bad = [v for v in verdicts if not v[3]]
    print("CONTROLS OK. %d evasion row(s) desynced." % len(bad))
    return 1 if bad else 0


def self_test():
    """Prove the harness can tell one response from two, against local fakes."""
    import os, tempfile, threading
    ok = True
    for name, nresp, expect in (("strict", 1, 1), ("desync", 2, 2)):
        p = "/tmp/f3st-%s-%d.sock" % (name, os.getpid())
        if os.path.exists(p):
            os.remove(p)
        srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        srv.bind(p); srv.listen(1)

        def serve(n=nresp):
            try:
                c, _ = srv.accept()
            except OSError:
                return
            c.recv(65536)
            c.sendall(b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\n{}" * n)
            c.close()

        threading.Thread(target=serve, daemon=True).start()
        raw = send(p, PING)
        got = count_responses(raw)
        good = got == expect
        ok = ok and good
        print("self-test %-8s upstream sent %d -> harness counted %d  %s"
              % (name, nresp, got, "OK" if good else "FAIL"))
        srv.close()
        if os.path.exists(p):
            os.remove(p)
    print("\nHARNESS %s" % ("DISCRIMINATES" if ok else "IS BROKEN — do not trust it"))
    return 0 if ok else 1


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--socket", default="/var/run/docker.sock")
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args()
    sys.exit(self_test() if a.self_test else run(a.socket))
```

## 4. Running it

```bash
# 0. Preconditions
test -f /opt/governance/control/mutation-enabled \
  && echo "KILL SWITCH PRESENT — stop, turn it off first" || echo "kill switch absent — OK"
docker version --format 'Server {{.Server.Version}} / Go {{.Server.GoVersion}}'   # record this

# 1. Prove the instrument, before trusting any result from it
python3 /tmp/f3-measure.py --self-test

# 2. Measure. Needs read access to the socket (docker group or root).
python3 /tmp/f3-measure.py --socket /var/run/docker.sock | tee /tmp/f3-results.txt
echo "exit: ${PIPESTATUS[0]}"   # NOT $? — that would be tee's
```

Exit codes: `0` no desync, `1` at least one row desynced, `2` controls misbehaved
(results void).

## 5. Results — FILL IN ON THE VPS

| | |
|---|---|
| Date run | |
| Docker Server version | |
| dockerd Go version | |
| Kill switch at run time | |
| `--self-test` verdict | |
| CONTROL-NEG / CONTROL-POS | |

| Row | Responses | Statuses | Desync? |
|---|---|---|---|
| OBS-FOLD | | | |
| TE-SPACE | | | |
| DUP-CL | | | |

## 6. What each outcome means, decided in advance

Deciding this now, before the numbers exist, is deliberate — it is how the result stops
being negotiable once someone wants the rail working.

- **Any row returns 2 responses → a live host-containment bypass**, in the same class as
  the C1 Critical, reachable by exactly the adversary the proxy exists to constrain (the
  design's §1: the proxy protects *the host* against *a compromised broker*, and a
  compromised broker can open the proxy socket and write arbitrary bytes). **Harden before
  the kill switch is ever turned on.** Not before deploy — before mutation is enabled.
- **All rows return 1 → not bypasses today.** Harden anyway, at normal priority: the
  proxy would still be relying on dockerd being stricter than Python, which is a property
  of a dependency and not of this codebase, and it is re-litigated on every Docker upgrade.
- **Controls misbehave → no conclusion.** Do not record a verdict, do not report "no
  desync found". Fix the harness and re-run.

## 7. The hardening this feeds, whichever way it goes

Refuse what cannot be parsed unambiguously, rather than forwarding a header block the
proxy did not fully understand:

1. Reject any header line beginning with a space or tab (obs-fold).
2. Reject any header name that is not a bare token immediately followed by `:`.
3. Reject duplicate `Content-Length` headers outright, rather than keeping the last.

This removes the dependency on dockerd's strictness instead of documenting it. Constraints:

- **Re-run the positive control.** A proxy that refuses everything passes every attacker
  test and breaks the production rail — this project has already shipped a seam review that
  blessed a seam nobody could pass.
- The 2026-09-16 endpoint measurement recorded **measured absence** of chunked request
  bodies in real traffic, not proof of impossibility. It never produced one, so this
  hardening costs nothing on the traffic actually observed — but that is an absence, and
  the VPS re-measurement is the chance to check it against Linux Docker rather than inherit
  it.
- Prove each new guard by making it fail. Three assertions in this wave passed for reasons
  unrelated to their claims, and reading found none of them.

**Applied 2026-09-23 (PR #48), without the §5 measurement, as §6 allows.** `_parse_head`
enforces all three rules above plus a fourth — no bare CR, LF or NUL anywhere in the head
(form 4) — and also requires exactly `HTTP/1.1` and printable-ASCII header values, and bounds
`Content-Length` to 19 digits (Go's `ParseUint` 63-bit maximum). The positive
control was re-run on Linux CI (run 35924147988: `bind-agreement: executed 6, skipped 0`, `ALLOW` on
create). §5 stays blank: the measurement is now informative, not a prerequisite.

## 8. Carry alongside: the end-to-end check F4 still owes

`65df9b1` made the proxy refuse **more** than it used to — a `Content-Length` that is not
`1*DIGIT` is now rejected, including an empty value that the old `or b"0"` fallback silently
coerced to `0`. Everything this wave has learned says to treat "the proxy now refuses more" as a
claim about the production rail that has to be tested, not assumed.

**What was verified on darwin:** the unit-level positive control
(`test_an_ordinary_allowed_request_with_only_content_length_still_reaches_upstream`) passes — an
ordinary request is still ALLOWED and still reaches the upstream — and Go's
`http.Request.Write`, which is what the Docker CLI and compose use, cannot emit any of the
refused forms.

**What was NOT verified, and why:** no end-to-end run of the real rail through the proxy. Docker
was not running on the dev machine. The 2026-09-16 endpoint measurement cannot settle it either
— it records method, path, connection and call counts, **not header blocks**, so it has nothing
to say about what `Content-Length` forms real traffic emits. That is an absence of evidence, not
evidence of absence.

**On the VPS**, alongside the endpoint re-measurement, run the real rail end to end through the
proxy (the shape of the implementation plan's Step 5) and confirm an ordinary mutation path is
still ALLOWED, in the proxy's own log, from end to end.

**If a real request is refused with `malformed Content-Length`: that is the finding.** Do not
widen the parse to make it pass. Identify which client emitted it and what it emitted first — a
legitimate client emitting a non-digit `Content-Length` would itself be worth understanding, and
the reflex to relax a check until the rail works is the same reflex that would have weakened the
`Cmd` policy when Task 3's positive control failed (`f80c939`).
