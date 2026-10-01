#!/usr/bin/env python3
"""Per-app chat-trigger broker (Option B spec 2026-09-30 §3.3). Stdlib only.

  hermes-app-broker.py --app ads-audit --watch --interval 2      (systemd: hermes-app-broker@ads-audit)

Runs as hermes-app-<app>: NoNewPrivileges, no capabilities, no network, no Docker, no sudo. It
reads the only tree the gateway writes (spool/apps/<app>/requests), so every byte is hostile.
It decides admission (schema, replay, kill switch, client status, quota — reserved BEFORE the
job exists) and writes a job file for the root runner; it never executes anything. Results are
built only by app_lib.map_done's whitelist. Nothing re-runs on its own: a reservation whose job
vanished is reported `interrupted`, never re-queued."""
import argparse, os, stat, sys, time
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import app_lib as A
import vault_lib as V

MAX_PER_PASS = 64
REQUEST_MAX_AGE = 3600


class Ctx:
    def __init__(self, manifest, spool, state, registry, now=A.utcnow, log=print):
        self.m, self.spool, self.state, self.registry, self.now, self.log = \
            manifest, spool, state, registry, now, log
        self.req_dir = os.path.join(spool, "requests")
        self.res_dir = os.path.join(spool, "results")
        self.ledger = A.Ledger(os.path.join(state, "state", "ledger.jsonl"))
        self.dir_noted = False

    def d(self, name):
        return os.path.join(self.state, name)


def _say(ctx, rid, op, client, status, reason):
    ctx.log(f"hermes-app-broker[{ctx.m.app}]: request={rid} op={op or '-'} client={client or '-'} "
            f"status={status} reason={reason or '-'}")


def _note(ctx, text):
    """A fixed-text journal line: never carries a hostile name or an exception message."""
    ctx.log(f"hermes-app-broker[{ctx.m.app}]: {text}")


def _rid_or_dash(rid):
    return rid if A.REQUEST_ID_RE.fullmatch(rid) else "-"


def _unlink(ctx, path):
    try:
        os.unlink(path)
    except FileNotFoundError:
        pass
    except OSError:
        _note(ctx, "error: could not remove a spool entry")


def _result(ctx, result):
    A.write_json_atomic(ctx.res_dir, result["request_id"] + ".json", result)
    _say(ctx, result["request_id"], result["op"], result["client"], result["status"], result["reason"])


def _active(ctx, client):
    try:
        rec = V.load_registry(ctx.registry).get(client)
    except (OSError, ValueError, AttributeError, TypeError):   # missing, unreadable or garbage
        return False
    return isinstance(rec, dict) and rec.get("status") == "active"


def _refuse(ctx, rid, op, client, reason):
    # The result FIRST: if it cannot be written nothing is recorded, and the request (still in
    # requests/) is retried next pass. Rewriting the same result on a retry is idempotent.
    _result(ctx, A.refused_result(rid, op, client, reason))
    ctx.ledger.append("refused", rid, op, client, now=ctx.now())


def _admit(ctx, req):
    rid, op, client = req["request_id"], req["op"], req["client"]
    if os.path.exists(ctx.d("DISABLED")):
        return _refuse(ctx, rid, op, client, "disabled")
    if not _active(ctx, client):
        return _refuse(ctx, rid, op, client, "inactive_client")
    day, q = ctx.now()[:10], ctx.m.ops[op]["quota"]
    if ("per_client_day" in q and ctx.ledger.count(day, op, client) >= q["per_client_day"]) or \
            ("per_box_day" in q and ctx.ledger.count(day, op) >= q["per_box_day"]):
        return _refuse(ctx, rid, op, client, "quota")
    ctx.ledger.append("reserved", rid, op, client, now=ctx.now())       # BEFORE the job exists
    try:
        A.write_json_atomic(ctx.d("jobs"), rid + ".json", {"job_id": rid, "op": op, "client": client},
                            mode=0o600)
    except Exception:
        # No job: close the reservation result-first (it still counts against the quota). If
        # even the result cannot be written, the reservation stays open for recover().
        _note(ctx, "error: a job file could not be written (request failed)")
        try:
            _result(ctx, A.refused_result(rid, op, client, "internal", status="failed"))
            ctx.ledger.append("resulted", rid, now=ctx.now())
        except Exception:
            _note(ctx, "error: a failed job could not be resulted (left for recover)")
        return
    _say(ctx, rid, op, client, "queued", None)


def _orphan_result(ctx, rid, op, client, p):
    """A result with no ledger line: a crash fell between a refusal's result write and its
    ledger append. Record it and drop the request; the first result stands, never re-decided."""
    if not os.path.lexists(os.path.join(ctx.res_dir, rid + ".json")):
        return False
    ctx.ledger.append("refused", rid, op, client, now=ctx.now())
    _say(ctx, rid, op, client, "dropped", "duplicate")
    _unlink(ctx, p)
    return True


def _handle_request(ctx, n):
    p = os.path.join(ctx.req_dir, n)
    rid = n[:-5]
    try:
        req = A.parse_request(A.read_capped(p, A.MAX_REQUEST_BYTES), n, ctx.m)
    except A.Refused:
        if A.REQUEST_ID_RE.fullmatch(rid) and not ctx.ledger.seen(rid):
            if _orphan_result(ctx, rid, None, None, p):
                return
            _refuse(ctx, rid, None, None, "bad_request")
        else:
            _say(ctx, _rid_or_dash(rid), None, None, "dropped", "bad_request")
        _unlink(ctx, p); return
    if ctx.ledger.seen(rid):
        _say(ctx, rid, req["op"], req["client"], "dropped", "duplicate")   # the first result stands
        _unlink(ctx, p); return
    if _orphan_result(ctx, rid, req["op"], req["client"], p):
        return
    _admit(ctx, req)
    _unlink(ctx, p)


def drain_once(ctx):
    try:
        names = os.listdir(ctx.req_dir)
    except FileNotFoundError:
        return
    now = time.time()
    todo = []
    for n in names:
        p = os.path.join(ctx.req_dir, n)
        try:
            st = os.lstat(p)
        except OSError:
            continue
        if stat.S_ISDIR(st.st_mode):
            # The gateway can mkdir here; a non-empty directory cannot be removed by us. Leave it,
            # say so once per process, and never let it stop a pass.
            try:
                os.rmdir(p)
            except OSError:
                if not ctx.dir_noted:
                    _note(ctx, "warning: a directory in requests/ cannot be removed (left in place)")
                    ctx.dir_noted = True
            continue
        if not A.FILENAME_RE.fullmatch(n):
            if not n.startswith(".") or now - st.st_mtime > REQUEST_MAX_AGE:   # keep in-flight temp files
                if not n.startswith("."):
                    _say(ctx, "-", None, None, "dropped", "bad_request")
                _unlink(ctx, p)
            continue
        if not stat.S_ISREG(st.st_mode):                                 # FIFO, symlink, socket, device
            _say(ctx, _rid_or_dash(n[:-5]), None, None, "dropped", "bad_request")
            _unlink(ctx, p); continue
        if now - st.st_mtime > REQUEST_MAX_AGE:
            _say(ctx, _rid_or_dash(n[:-5]), None, None, "dropped", "expired")
            _unlink(ctx, p); continue
        todo.append((st.st_mtime, n))
    for _, n in sorted(todo)[:MAX_PER_PASS]:
        try:
            _handle_request(ctx, n)
        except Exception:                                # one entry costs one line, never the pass
            _note(ctx, "error: a request could not be processed (left for the next pass)")


def _collect_one(ctx, n, open_):
    p = os.path.join(ctx.d("done"), n)
    rid = n[:-5]
    try:
        done = A.parse_done(A.read_capped(p, A.MAX_DONE_BYTES), n)
    except A.Refused:
        done = None
    # Only an id this broker reserved and has not yet resulted gets a result: the first
    # result stands, and `released` can never be written twice or for a foreign id.
    if not A.FILENAME_RE.fullmatch(n) or rid not in open_:
        _unlink(ctx, p); return
    op, client = open_.pop(rid)
    req = {"request_id": rid, "op": op, "client": client}
    if done is None:
        result = A.refused_result(rid, op, client, "internal", status="failed")
    else:
        result = A.map_done(req, done, ctx.m)
    # The result FIRST, then close the ledger, then drop the done file: a failure at any point
    # leaves the reservation open and the done file in place, so the next pass retries.
    _result(ctx, result)
    if result["status"] == "busy":
        ctx.ledger.append("released", rid, now=ctx.now())
    ctx.ledger.append("resulted", rid, now=ctx.now())
    _unlink(ctx, p)


def collect_once(ctx):
    now = time.time()
    open_ = {r: (o, c) for r, o, c in ctx.ledger.unresolved()}      # once per pass
    for n in sorted(os.listdir(ctx.d("done"))):
        p = os.path.join(ctx.d("done"), n)
        if n.startswith("."):                      # the runner's in-flight atomic-write temp file
            try:
                if now - os.lstat(p).st_mtime > REQUEST_MAX_AGE:
                    _unlink(ctx, p)
            except FileNotFoundError:
                pass
            continue
        try:
            _collect_one(ctx, n, open_)
        except Exception:
            _note(ctx, "error: a done file could not be collected (left for the next pass)")


def recover(ctx):
    for rid, op, client in ctx.ledger.unresolved():
        name = rid + ".json"
        if any(os.path.exists(os.path.join(ctx.d(d), name)) for d in ("jobs", "running", "done")):
            continue
        try:
            _result(ctx, A.refused_result(rid, op, client, "interrupted", status="failed"))
            ctx.ledger.append("resulted", rid, now=ctx.now())
        except Exception:
            _note(ctx, "error: an interrupted reservation could not be resulted (retried at next recover)")


def expire_results(ctx, max_age=7 * 86400):
    now = time.time()
    for n in os.listdir(ctx.res_dir):
        p = os.path.join(ctx.res_dir, n)
        try:
            if now - os.lstat(p).st_mtime > max_age:
                os.unlink(p)
        except FileNotFoundError:
            pass


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--app", required=True)
    ap.add_argument("--manifest-dir", default="/opt/hermes-agent/registry/apps")
    ap.add_argument("--apps-root", default="/var/lib/hermes/spool/apps")
    ap.add_argument("--state-root", default="/var/lib/hermes/app-state")
    ap.add_argument("--registry", default="/var/lib/hermes/governance/registry/clients.json")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--once", action="store_true")
    g.add_argument("--watch", action="store_true")
    ap.add_argument("--interval", type=float, default=2.0)
    a = ap.parse_args(argv)
    m = A.load_manifest(os.path.join(a.manifest_dir, a.app + ".json"), a.app)
    ctx = Ctx(m, A.spool_dir(a.app, a.apps_root), A.state_dir(a.app, a.state_root), a.registry,
              log=lambda s: print(s, flush=True))
    recover(ctx)
    while True:
        drain_once(ctx)
        collect_once(ctx)
        expire_results(ctx)
        if a.once:
            return 0
        time.sleep(a.interval)


if __name__ == "__main__":
    sys.exit(main())
