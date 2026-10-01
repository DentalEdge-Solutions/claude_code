#!/usr/bin/env python3
"""The per-app chat-trigger contract (Option B spec 2026-09-30 §2-§3). Stdlib only.

Everything the gateway client, the broker and the runner must agree on lives here, once:
the manifest, the four file schemas (request, job, done, result), the result whitelist, the
quota ledger and the atomic writer. Every parser treats its input as hostile: closed key sets,
byte caps, O_NOFOLLOW, regular-file checks. Nothing here decides policy (quota, kill switch,
client status) — that is the broker's; nothing here executes anything — that is the runner's."""
import collections, datetime, json, os, re, stat, tempfile, uuid

import governance_lib
from client_audit_lib import TS_RE

SLUG_RE = governance_lib.SLUG_RE
REQUEST_ID_RE = governance_lib.REQUEST_ID_RE
APP_RE = re.compile(r"^[a-z][a-z0-9-]{0,31}$")
FILENAME_RE = re.compile(r"^[0-9a-f-]{36}\.json$")
_ARG_RE = re.compile(r"^--[a-z][a-z-]{0,31}$")
_TOOL_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
MAX_REQUEST_BYTES, MAX_JOB_BYTES, MAX_MANIFEST_BYTES = 1024, 512, 16384
MAX_STDOUT = 65536
MAX_DONE_BYTES = MAX_STDOUT * 2 + 1024      # JSON-escaped stdout plus the envelope
SPOOL_FILE_MODE = 0o640
KNOWN_OPS = ("run", "list")
STATUSES = ("ok", "refused", "failed", "busy")
STEP_CLASSES = ("collect", "snapshot", "read", "proxy", "draft", "isolation", "vault-write")
BROKER_REASONS = ("bad_request", "duplicate", "inactive_client", "quota", "disabled",
                  "timeout", "interrupted", "internal")
COMMAND_REASONS = ("precheck", "busy", "internal") + STEP_CLASSES
LIST_LIMIT = 24
RC_STATUS = {0: "ok", 1: "failed", 2: "refused", 3: "busy"}
# The only reasons each status may carry. A contradictory pair (busy + vault-write) is out of
# contract and becomes failed/internal.
STATUS_REASONS = {"ok": (None,), "busy": ("busy",), "refused": ("precheck",),
                  "failed": STEP_CLASSES + ("internal",)}
_TS_BODY = TS_RE.pattern[1:-1]      # TS_RE without its ^...$ anchors, never restated
assert TS_RE.pattern == "^" + _TS_BODY + "$"

Manifest = collections.namedtuple("Manifest", "app user command ops tools wait_seconds")


class Refused(ValueError):
    def __init__(self, detail, reason="bad_request"):
        super().__init__(detail)
        self.reason = reason


def spool_dir(app, root="/var/lib/hermes/spool/apps"):
    return os.path.join(root, app)


def state_dir(app, root="/var/lib/hermes/app-state"):
    return os.path.join(root, app)


def read_capped(path, cap):
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except OSError as e:
        raise Refused(f"cannot open: {type(e).__name__}")
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode):
            raise Refused("not a regular file")
        if st.st_size > cap:
            raise Refused("too large")
        data = os.read(fd, cap + 1)
        if len(data) > cap:
            raise Refused("too large")
        return data
    finally:
        os.close(fd)


def _json(data):
    try:
        return json.loads(data)
    except (ValueError, UnicodeDecodeError):
        raise Refused("not JSON")


def _int(v, lo, hi):
    return isinstance(v, int) and not isinstance(v, bool) and lo <= v <= hi


def load_manifest(path, app):
    if not APP_RE.fullmatch(app):
        raise ValueError("invalid app name")
    with open(path, "rb") as f:
        raw = f.read(MAX_MANIFEST_BYTES + 1)
    if len(raw) > MAX_MANIFEST_BYTES:
        raise ValueError("manifest too large")
    d = json.loads(raw)
    if set(d) != {"app", "user", "command", "ops", "tools", "wait_seconds"}:
        raise ValueError("manifest keys")
    if d["app"] != app or d["user"] != "hermes-app-" + app:
        raise ValueError("manifest app/user")
    if not isinstance(d["command"], str) or not os.path.isabs(d["command"]) or " " in d["command"]:
        raise ValueError("manifest command must be an absolute path")
    ops = d["ops"]
    if not isinstance(ops, dict) or not ops or not set(ops) <= set(KNOWN_OPS):
        raise ValueError("manifest ops")
    for name, op in ops.items():
        if set(op) != {"args", "timeout", "quota"} or not isinstance(op["args"], list) \
                or not all(isinstance(x, str) and _ARG_RE.fullmatch(x) for x in op["args"]) \
                or not _int(op["timeout"], 1, 7200) or not isinstance(op["quota"], dict) \
                or not set(op["quota"]) <= {"per_client_day", "per_box_day"} \
                or not all(_int(v, 1, 1000) for v in op["quota"].values()):
            raise ValueError(f"manifest op {name!r}")
    tools = d["tools"]
    if not isinstance(tools, dict) or set(tools) != set(ops) | {"status"} \
            or not all(isinstance(v, str) and _TOOL_RE.fullmatch(v) for v in tools.values()) \
            or len(set(tools.values())) != len(tools):
        raise ValueError("manifest tools")
    ws = d["wait_seconds"]
    if not isinstance(ws, dict) or set(ws) != set(ops) or not all(_int(v, 1, 600) for v in ws.values()):
        raise ValueError("manifest wait_seconds")
    return Manifest(d["app"], d["user"], d["command"], ops, tools, ws)


def _slug(v):
    return isinstance(v, str) and SLUG_RE.fullmatch(v) is not None


def parse_request(data, filename, manifest):
    if not FILENAME_RE.fullmatch(filename):
        raise Refused("bad filename")
    d = _json(data)
    if not isinstance(d, dict) or set(d) != {"request_id", "app", "op", "client"}:
        raise Refused("bad keys")
    if not isinstance(d["request_id"], str) or not REQUEST_ID_RE.fullmatch(d["request_id"]) \
            or d["request_id"] + ".json" != filename:
        raise Refused("bad request_id")
    if d["app"] != manifest.app or not isinstance(d["op"], str) or d["op"] not in manifest.ops \
            or not _slug(d["client"]):
        raise Refused("bad app/op/client")
    return d


def make_request(manifest, op, client):
    d = {"request_id": str(uuid.uuid4()), "app": manifest.app, "op": op, "client": client}
    return parse_request(json.dumps(d).encode(), d["request_id"] + ".json", manifest)


def parse_job(data, filename):
    if not FILENAME_RE.fullmatch(filename):
        raise Refused("bad filename")
    d = _json(data)
    if not isinstance(d, dict) or set(d) != {"job_id", "op", "client"} \
            or not isinstance(d["job_id"], str) or d["job_id"] + ".json" != filename \
            or d["op"] not in KNOWN_OPS or not _slug(d["client"]):
        raise Refused("bad job")
    return d


def parse_done(data, filename):
    if not FILENAME_RE.fullmatch(filename):
        raise Refused("bad filename")
    d = _json(data)
    if not isinstance(d, dict) or set(d) != {"job_id", "rc", "stdout", "timed_out", "interrupted"} \
            or not isinstance(d["job_id"], str) or d["job_id"] + ".json" != filename \
            or not (d["rc"] is None or _int(d["rc"], -255, 255)) \
            or not isinstance(d["stdout"], str) or len(d["stdout"]) > MAX_STDOUT \
            or not isinstance(d["timed_out"], bool) or not isinstance(d["interrupted"], bool):
        raise Refused("bad done")
    return d


def _base(request_id, op, client, status, reason):
    return {"request_id": request_id, "op": op, "client": client, "status": status, "reason": reason}


def refused_result(request_id, op, client, reason, status="refused"):
    r = _base(request_id, op, client, status, reason)
    if op == "list":
        r["audits"] = []
    else:
        r.update(exit_code=None, ts=None, steps=[], vault_path=None)
    return r


def _one_json_line(stdout):
    lines = [l for l in stdout.splitlines() if l.strip()]
    if len(lines) != 1:
        raise Refused("stdout is not exactly one line")
    d = _json(lines[0])
    if not isinstance(d, dict):
        raise Refused("stdout is not an object")
    return d


def _run_result(req, rc, p):
    if set(p) != {"status", "reason", "exit_code", "ts", "steps", "vault_path"}:
        raise Refused("keys")
    if rc not in RC_STATUS or RC_STATUS[rc] != p["status"] or p["exit_code"] != rc:
        raise Refused("status/rc")
    if p["reason"] not in STATUS_REASONS[p["status"]]:
        raise Refused("reason")
    if not (p["ts"] is None or (isinstance(p["ts"], str) and TS_RE.fullmatch(p["ts"]))):
        raise Refused("ts")
    steps = p["steps"]
    if not isinstance(steps, list) or len(steps) > len(STEP_CLASSES) or not all(
            isinstance(s, dict) and set(s) == {"name", "rc", "seconds"} and s["name"] in STEP_CLASSES
            and _int(s["rc"], -255, 255) and isinstance(s["seconds"], (int, float))
            and not isinstance(s["seconds"], bool) and 0 <= s["seconds"] < 86400 for s in steps):
        raise Refused("steps")
    vp = p["vault_path"]
    if vp is not None:
        want = re.compile("/var/lib/hermes/vaults/" + re.escape(req["client"])
                          + "/audits/(" + _TS_BODY + r")-audit\.md")
        mt = want.fullmatch(vp) if isinstance(vp, str) else None
        if mt is None or mt.group(1) != p["ts"] or p["status"] != "ok":
            raise Refused("vault_path")
    r = _base(req["request_id"], "run", req["client"], p["status"], p["reason"])
    r.update(exit_code=rc, ts=p["ts"], steps=[dict(s) for s in steps], vault_path=vp)
    return r


def _list_result(req, rc, p):
    if rc == 0 and set(p) == {"status", "audits"} and p["status"] == "ok" \
            and isinstance(p["audits"], list) and len(p["audits"]) <= LIST_LIMIT \
            and all(isinstance(t, str) and TS_RE.fullmatch(t) for t in p["audits"]):
        r = _base(req["request_id"], "list", req["client"], "ok", None)
        r["audits"] = list(p["audits"])
        return r
    if rc == 2 and p == {"status": "refused", "reason": "precheck"}:
        return refused_result(req["request_id"], "list", req["client"], "precheck")
    raise Refused("list payload")


def map_done(req, done, manifest):
    """The ONLY way command output becomes a result. Anything outside the contract is
    failed/internal, and nothing from the stdout is passed through."""
    rid, op, client = req["request_id"], req["op"], req["client"]
    if done["interrupted"]:
        return refused_result(rid, op, client, "interrupted", status="failed")
    if done["timed_out"]:
        return refused_result(rid, op, client, "timeout", status="failed")
    try:
        p = _one_json_line(done["stdout"])
        return _run_result(req, done["rc"], p) if op == "run" else _list_result(req, done["rc"], p)
    except Refused:
        return refused_result(rid, op, client, "internal", status="failed")


def write_json_atomic(dirpath, name, obj, mode=SPOOL_FILE_MODE, uid=None, gid=None):
    fd, tmp = tempfile.mkstemp(dir=dirpath, prefix="." + name + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            if uid is not None:
                os.fchown(f.fileno(), uid, -1 if gid is None else gid)
            os.fchmod(f.fileno(), mode)
            json.dump(obj, f, sort_keys=True)
            f.flush(); os.fsync(f.fileno())
        os.replace(tmp, os.path.join(dirpath, name))
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def utcnow():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class Ledger:
    """Append-only JSONL: one line per reserved/released/resulted/refused event. Host-only
    (app-state/<app>/state/ledger.jsonl, never mounted). A torn last line is ignored."""

    def __init__(self, path):
        self.path = path

    def _events(self):
        try:
            with open(self.path, encoding="utf-8") as f:
                for line in f:
                    try:
                        e = json.loads(line)
                    except ValueError:
                        continue
                    if isinstance(e, dict) and isinstance(e.get("request_id"), str):
                        yield e
        except FileNotFoundError:
            return

    def append(self, event, request_id, op=None, client=None, now=None):
        now = now or utcnow()
        line = json.dumps({"event": event, "request_id": request_id, "op": op, "client": client,
                           "at": now, "day": now[:10]}, sort_keys=True) + "\n"
        fd = os.open(self.path, os.O_RDWR | os.O_APPEND | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        try:
            size = os.fstat(fd).st_size
            if size and os.pread(fd, 1, size - 1) != b"\n":
                # A crash left a torn last line: terminate it, or this event would be glued
                # onto the fragment and skipped by _events (a lost reservation).
                line = "\n" + line
            os.write(fd, line.encode("utf-8")); os.fsync(fd)
        finally:
            os.close(fd)

    def seen(self, rid):
        return any(e.get("request_id") == rid for e in self._events())

    def reserved(self, rid):
        for e in self._events():
            if e.get("request_id") == rid and e.get("event") == "reserved":
                return e.get("op"), e.get("client")
        return None

    def count(self, day, op, client=None):
        # In file order: a release cancels only a reservation that appears EARLIER.
        res = set()
        for e in self._events():
            if e.get("event") == "reserved" and e.get("day") == day and e.get("op") == op \
                    and (client is None or e.get("client") == client):
                res.add(e["request_id"])
            elif e.get("event") == "released":
                res.discard(e["request_id"])
        return len(res)

    def unresolved(self):
        # In file order, like count(): a close cancels only an EARLIER reservation.
        open_ = {}
        for e in self._events():
            if e.get("event") == "reserved":
                open_[e["request_id"]] = (e["request_id"], e.get("op"), e.get("client"))
            elif e.get("event") in ("resulted", "released"):
                open_.pop(e["request_id"], None)
        return list(open_.values())
