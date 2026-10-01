#!/usr/bin/env python3
"""One client's Google Ads trend-audit DRAFT on the box (spec 2026-09-29 ads-audits-on-the-box).

  sudo run-client-audit <client> [--dry-run] [--json]
  sudo run-client-audit <client> --list --json

--json: exactly one JSON line on stdout (the broker's contract, Option B §3.5), every human line
on stderr. --list: this client's audit timestamps (newest 24), no lock taken.

Pre-checks, then: collect (one-shot ads-collector) -> snapshot (host) -> readers (one-shot
ads-reader) -> egress-proxy up -> draft (claude -p in the one-shot ads-drafter, which sees only
this client's vault, reports and draft-out dirs) -> the check that the draft names no other
client -> vault-write. The proxy is stopped (its decision log kept as proxy.log first) and the
transient draft removed on every exit, a SIGTERM from the host runner's timeout included (§7).
Stops at the first failure. Exit: 0 draft written, 1 a step failed, 2 a pre-check refused,
3 another audit is running.
Nothing shown carries a customer id or credential value; each step's stdout and stderr go to
/var/lib/hermes/audit-logs/<client>/<step>.{stdout,stderr} (root 0600; snapshot.stdout is handed
to uid 10000 for vault-write). The logs are OUTSIDE the tree the collector mounts rw, and every
file there is created O_EXCL|O_NOFOLLOW: root never follows a container-planted symlink."""
import argparse, datetime, json, os, re, signal, stat, subprocess, sys, time
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import changeset_lib as C
import client_audit_lib as L
import review_lib as R

AGENT_DIR = "/opt/hermes-agent"
GOV = "/var/lib/hermes/governance"
REGISTRY = GOV + "/registry/clients.json"
CRED = "/etc/hermes/.env" + ".ga"
APP_DIR = "/opt/projects/claude-google-ads"
AUDIT_DATA = "/var/lib/hermes/audit-data"
AUDIT_LOGS = "/var/lib/hermes/audit-logs"   # root-only; never mounted into anything
VAULTS = "/var/lib/hermes/vaults"           # Option B §4: client data out of the gateway
REPORTS = "/var/lib/hermes/reports"
DRAFT_OUT = "/var/lib/hermes/draft-out"
ANTHROPIC_CRED = "/etc/hermes/.env" + ".anthropic"
HOST_PARENTS = (VAULTS, REPORTS, DRAFT_OUT)
LOCK = "/run/lock/hermes-client-audit.lock"
PROJECT = "claude_google_ads"
TS_FMT = "%Y-%m-%d_%H-%M-%S"   # file names; the snapshot gets the same instant in ISO (M8)
COLLECTORS = ("audit_discovery", "negatives_audit", "audit_assets_rsa", "assess_supplemental")
READERS = ("account_overview", "audit_search_terms", "audit_analyze")
CLEANUP_TIMEOUT = 20          # each cleanup command (logs capture, rm -sf, rm -f): bounded inside the runner's grace
TIMEOUTS = {"collect": 900, "snapshot": 120, "read": 300, "proxy": 60, "draft": 1200, "vault-write": 120}
CRED_NAMES = ("GOOGLE_ADS_DEVELOPER_TOKEN", "GOOGLE_ADS_CLIENT_ID", "GOOGLE_ADS_CLIENT_SECRET",
              "GOOGLE_ADS_REFRESH_TOKEN", "GOOGLE_ADS_LOGIN_CUSTOMER_ID", "GOOGLE_ADS_CUSTOMER_ID")
OWNER_UID = 0                 # the credential file's owner; tests override
DATA_UID = DATA_GID = 10000   # the containers' uid; tests set None to skip chown
PIN_OVERRIDE = None           # tests only
# vault-write runs on the HOST but writes files the drafter (uid 10000) must read next month
# (trend mode): run it AS that uid, or the vault fills with root-owned files. The snapshot runs
# as that uid too: it reads files the collector container controls (F2). Tests set [].
RUN_AS_DATA_UID = ["setpriv", "--reuid=10000", "--regid=10000", "--clear-groups"]

# Verbatim from run-trend-audit.sh (spec §2 step 5): the analyst, its model and its limits.
# One change (I2): `timeout -k 30 1150` stops claude INSIDE the container before the host's
# 1200 s timeout, which can only kill the `docker compose run` client (the named container is
# then removed, I2); -k 30 sends SIGKILL if claude ignores SIGTERM, still inside 1200 s (F3).
# Option B: the paths are the ads-drafter's mounts (/work/vault ro, /work/reports ro, /work/out).
DRAFT_SCRIPT = r'''
  set -eu
  skill="/opt/skills/claude-code-ads-analyst/SKILL.md"
  vault="/work/vault"; reports="/work/reports"
  ls "$reports"/*.md >/dev/null 2>&1 || { echo "no reports for $PROJECT" >&2; exit 1; }
  out="/work/out/$TS-audit.md"
  timeout -k 30 1150 claude -p "Read and follow $skill EXACTLY, INCLUDING its Trend mode. Produce the Google Ads audit DRAFT for project $PROJECT. Fresh scrubbed reports: $reports/. THIS client'\''s prior history (read for trend deltas): $vault/metrics/, $vault/audits/, $vault/timeline.md (may be empty on the first run = establish baseline). SOP/benchmark docs: /projects/$PROJECT/. Read ONLY within $vault, $reports, and /projects/$PROJECT. Do NOT attempt ExitPlanMode and do NOT narrate your tools or environment; BEGIN your response with the DRAFT banner and output ONLY the deliverable markdown." \
    --allowedTools "Read,Grep,Glob" --permission-mode plan --model claude-opus-4-8 > "$out"
  echo "$out"
'''


def step_name(argv):
    if "ads-collector" in argv:
        return "collect:" + os.path.basename(argv[-1])[:-3]
    if "ads-reader" in argv:
        return "read:" + argv[argv.index("--report") + 1]
    if "ads-drafter" in argv:
        return "draft"
    if "egress-proxy" in argv and "up" in argv:
        return "proxy"
    return "snapshot" if any(a.endswith("ads-metrics-snapshot.py") for a in argv) else "vault-write"
    # (snapshot and vault-write argvs may start with RUN_AS_DATA_UID; neither test looks at argv[0])


STEP_CLASSES = ("collect", "snapshot", "read", "proxy", "draft", "isolation", "vault-write")
LIST_LIMIT = 24


def step_class(name):
    return name.split(":", 1)[0]


def json_result(status, reason, rc, ts, results, vault_path):
    agg = {}
    for name, r, secs in results:
        c = step_class(name)
        prev = agg.get(c, {"name": c, "rc": 0, "seconds": 0.0})
        r_int = r if isinstance(r, int) else 1
        agg[c] = {"name": c, "rc": max(prev["rc"], r_int), "seconds": round(prev["seconds"] + secs, 1)}
    steps = [agg[c] for c in STEP_CLASSES if c in agg]
    return json.dumps({"status": status, "reason": reason, "exit_code": rc, "ts": ts,
                       "steps": steps, "vault_path": vault_path}, sort_keys=True)


def open_log(path):
    """A NEW 0600 log file; refuses (OSError) anything already there, a symlink included."""
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    return os.fdopen(fd, "w")


# draft-out/<slug> and vaults/<slug> are uid 10000's (the drafter and vault-write write them), so
# any name below the root-owned 0711 parent can be a planted symlink: reach them only through
# L.open_dir_below and act relative to that fd (F1).
def read_transient(root, slug, ts):
    fd = L.open_dir_below(root + DRAFT_OUT, (slug,))
    if fd is None:
        raise FileNotFoundError("the transient draft is missing")
    try:
        ffd = os.open(f"{ts}-audit.md", os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
    finally:
        os.close(fd)
    with os.fdopen(ffd, encoding="utf-8", errors="replace") as f:
        if not stat.S_ISREG(os.fstat(ffd).st_mode):
            raise L.UnsafePathError("the transient draft is not a regular file")
        return f.read()


def remove_transient(root, slug, ts):
    fd = L.open_dir_below(root + DRAFT_OUT, (slug,))
    if fd is None:
        return
    try:
        os.unlink(f"{ts}-audit.md", dir_fd=fd)
    except FileNotFoundError:
        pass
    finally:
        os.close(fd)


def vault_draft_is_file(root, slug, ts):
    fd = L.open_dir_below(root + VAULTS, (slug, "audits"))
    if fd is None:
        return False
    try:
        return stat.S_ISREG(os.stat(f"{ts}-audit.md", dir_fd=fd, follow_symlinks=False).st_mode)
    except FileNotFoundError:
        return False
    finally:
        os.close(fd)


def stop_proxy(root, logs, say):
    """Always called from _run's finally; harmless when the proxy never started. The proxy's
    host/decision/byte-count log (§5.2) lives only in the container: capture it into
    <logs>/proxy.log (open_log: new, 0600, never a planted symlink) BEFORE `rm -sf` destroys it,
    with both return codes. A failed rm is a warning on screen: the proxy may still be up."""
    compose = _compose(root)
    path = os.path.join(logs, "proxy.log")
    try:
        f = open_log(path)
    except OSError as e:
        f = None
        say(f"run-client-audit: WARNING: cannot create {path} ({type(e).__name__}); "
            f"the egress-proxy decision log is not kept")
    try:
        if f is not None:
            try:
                logs_rc = subprocess.run(compose + ["logs", "--no-color", "egress-proxy"], stdout=f, stderr=f,
                                         timeout=CLEANUP_TIMEOUT).returncode
            except (subprocess.TimeoutExpired, OSError) as e:
                logs_rc = type(e).__name__
            f.write(f"\n[run-client-audit] docker compose logs rc {logs_rc}\n")
            f.flush()
        rm_rc = _quiet(compose + ["rm", "-sf", "egress-proxy"])
        if f is not None:
            f.write(f"[run-client-audit] docker compose rm -sf egress-proxy rc {rm_rc}\n")
    finally:
        if f is not None:
            f.close()
    if rm_rc != 0:
        say(f"run-client-audit: WARNING: stopping egress-proxy failed (rc {rm_rc}); see {path} "
            f"and run `docker compose rm -sf egress-proxy`")
    return rm_rc


def _quiet(argv):
    try:
        return subprocess.run(argv, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                              timeout=CLEANUP_TIMEOUT).returncode
    except (subprocess.TimeoutExpired, OSError) as e:
        return type(e).__name__


def _on_sigterm(signum, frame):
    """The host runner's timeout sends SIGTERM (SIGKILL after a grace). Python's default exits
    without running `finally`; raising SystemExit(143) unwinds through _run's finally (transient
    draft, proxy) and real_runner's named-container removal. One-shot: a second TERM must not cut
    that cleanup short."""
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
    raise SystemExit(128 + signal.SIGTERM)


def real_runner(argv, env, timeout, out, err, cleanup=None):
    """out/err are the open log files (open_log); nothing is re-opened by path. A timeout kills
    only the `docker compose` client, so a named `run` container is removed explicitly (I2):
    it must not keep writing into the next client's reports."""
    try:
        return subprocess.run(argv, env=env, stdout=out, stderr=err, timeout=timeout).returncode
    except subprocess.TimeoutExpired:
        err.write(f"\n[run-client-audit] timed out after {timeout}s\n")
        _remove_named(argv, err, cleanup)
        return 124
    except (SystemExit, KeyboardInterrupt):     # SIGTERM (_on_sigterm) or ^C mid-step: same removal
        err.write("\n[run-client-audit] interrupted\n")
        _remove_named(argv, err, cleanup)
        raise


def _remove_named(argv, err, cleanup):
    if "--name" in argv:
        name = argv[argv.index("--name") + 1]
        rc = (cleanup or _quiet)(["docker", "rm", "-f", name])
        err.write(f"[run-client-audit] docker rm -f {name}: rc {rc}\n")
    err.flush()


def _iso(ts):
    """ts is validated here: it reaches container names, the draft's env and file names."""
    if not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}_[0-9]{2}-[0-9]{2}-[0-9]{2}", ts):
        raise ValueError("invalid run timestamp")
    return datetime.datetime.strptime(ts, TS_FMT).strftime("%Y-%m-%dT%H:%M:%SZ")


def _compose(root):
    # /opt/hermes-agent is a SYMLINK into the checkout. compose resolves the file's relative
    # binds (../../../claude-google-ads, ../..) from the directory named in -f WITHOUT following
    # it, so the unresolved path mounted /claude-google-ads and would have mounted / (first box
    # run, 2026-09-30). Pass the real path; the project name stays "hermes-agent".
    return ["docker", "compose", "-f", os.path.realpath(root + AGENT_DIR + "/docker-compose.yml"),
            "--profile", "tools"]


def plan(rec, ts, root):
    """[(timeout_key, argv, env)] — env holds only what the step needs, plus PATH."""
    slug, cid = rec["slug"], rec["customer_id"]
    collected_at = _iso(ts)
    data = AUDIT_DATA + "/" + slug
    base = {"PATH": os.environ.get("PATH", "/usr/sbin:/usr/bin:/sbin:/bin")}
    cred = {**base, **{k: v for k, v in L.load_cred_env(root + CRED).items() if k in CRED_NAMES},
            "GOOGLE_ADS_CUSTOMER_ID": cid, "HERMES_AUDIT_DATA_DIR": data,
            "HERMES_REPORTS_DIR": REPORTS + "/" + slug}
    eflags = [x for n in CRED_NAMES for x in ("-e", n)]
    named = lambda step: _compose(root) + ["run", "--rm", "--no-deps", "-T", "--name", f"hermes-audit-{ts}-{step}"]
    run = lambda step: named(step) + eflags          # Google credential: collector and reader ONLY
    steps = [("collect", run(f"collect-{c}") + ["ads-collector", f"code/{c}.py"], cred) for c in COLLECTORS]
    # The snapshot reads collector-controlled audit-data/<slug>/*.json: never as root (F2). Its
    # stdout is still the root-created, fchown'd snapshot.stdout fd.
    steps.append(("snapshot", RUN_AS_DATA_UID + ["python3", root + AGENT_DIR + "/bin/ads-metrics-snapshot.py",
                               "--audit-data", root + data, "--customer", cid, "--collected-at", collected_at], base))
    steps += [("read", run(f"read-{r}") + ["ads-reader", "--report", r, "--project", PROJECT], cred)
              for r in READERS]
    steps.append(("proxy", _compose(root) + ["up", "-d", "--no-deps", "egress-proxy"], base))
    key = L.load_env_value(root + ANTHROPIC_CRED, "ANTHROPIC_API_KEY") or ""
    draft_env = {**base, "ANTHROPIC_API_KEY": key, "HERMES_VAULT_DIR": VAULTS + "/" + slug,
                 "HERMES_REPORTS_DIR": REPORTS + "/" + slug, "HERMES_DRAFT_OUT_DIR": DRAFT_OUT + "/" + slug}
    # Non-secret, validated values inline (M9): slug (eligible_client), PROJECT (constant), ts (_iso).
    steps.append(("draft", named("draft") + ["-e", "ANTHROPIC_API_KEY", "-e", f"PROJECT={PROJECT}",
                                             "-e", f"CLIENT={slug}", "-e", f"TS={ts}",
                                             "ads-drafter", DRAFT_SCRIPT], draft_env))
    steps.append(("vault-write", RUN_AS_DATA_UID + ["python3", root + AGENT_DIR + "/bin/vault-write.py", "--client", slug,
                                  "--audit-file", root + f"{DRAFT_OUT}/{slug}/{ts}-audit.md",
                                  "--metrics-file", root + AUDIT_LOGS + "/" + slug + "/snapshot.stdout", "--ts", ts,
                                  "--registry", root + REGISTRY],
                  {**base, "VAULT_ROOT": root + VAULTS, "TS": ts}))
    return steps


def main(argv=None, runner=None, root="/", now=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("client")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--json", action="store_true")    # exactly one JSON line on stdout (the broker's contract)
    ap.add_argument("--list", action="store_true")    # this client's audit timestamps; takes no lock
    a = ap.parse_args(argv)
    if a.list and not a.json:
        ap.error("--list requires --json")
    root = root.rstrip("/")
    runner = runner or real_runner
    ts = now or datetime.datetime.now(datetime.timezone.utc).strftime(TS_FMT)
    human = sys.stderr if a.json else sys.stdout      # with --json every human line goes to stderr

    def emit(status, reason, rc, results=(), vault_path=None):
        """The single exit point of a run: with --json, its one stdout line."""
        if a.json:
            print(json_result(status, reason, rc, ts if status != "refused" else None, list(results), vault_path))
        return rc

    LIST_INTERNAL = json.dumps({"status": "failed", "reason": "internal"}, sort_keys=True)

    def unexpected(e, results=()):
        """--json only (plain mode re-raises): an exception outside the caught tuples still ends
        in one JSON line. Only the type name is shown: the message may carry a customer id."""
        print(f"run-client-audit: failed: unexpected {type(e).__name__}", file=sys.stderr)
        if a.list:
            print(LIST_INTERNAL); return 1
        return emit("failed", "internal", 1, results)

    try:
        rec = L.eligible_client(a.client, root + REGISTRY)
    except (L.PrecheckError, ValueError, OSError, TypeError, AttributeError) as e:   # M12: malformed entry
        print(f"run-client-audit: refused: {e}", file=sys.stderr)
        if a.list:
            print(json.dumps({"status": "refused", "reason": "precheck"}, sort_keys=True)); return 2
        return emit("refused", "precheck", 2)
    except Exception as e:          # not BaseException: KeyboardInterrupt/SystemExit propagate
        if not a.json:
            raise
        return unexpected(e)
    red = R.Redactor([], [rec["customer_id"]])
    say = lambda s: print(red.text(s), file=human)
    if a.list:
        try:
            fd = L.open_dir_below(root + VAULTS, (rec["slug"], "audits"))
            audits = []
            if fd is not None:
                try:
                    audits = L.list_audit_ts(fd)[-LIST_LIMIT:]
                finally:
                    os.close(fd)
        except OSError as e:     # an entry vanished between listdir and stat (container-controlled dir)
            print(red.text(f"run-client-audit: list failed: {type(e).__name__}: {e}"), file=sys.stderr)
            print(LIST_INTERNAL); return 1
        except Exception as e:      # --list implies --json
            return unexpected(e)
        print(json.dumps({"status": "ok", "audits": audits}, sort_keys=True))
        return 0
    try:
        L.check_secret_file(root + CRED, uid=OWNER_UID, mode=0o400)
        L.check_secret_file(root + ANTHROPIC_CRED, uid=OWNER_UID, mode=0o400)
        if L.anthropic_key_state(root + ANTHROPIC_CRED) != "real":
            raise L.PrecheckError(f"{ANTHROPIC_CRED} holds no real Anthropic key")
        for parent in HOST_PARENTS:
            L.check_host_parent(root + parent, uid=OWNER_UID)
        L.check_client_dir(root + VAULTS + "/" + rec["slug"],
                           uid=os.geteuid() if DATA_UID is None else DATA_UID)
        pin = PIN_OVERRIDE or C.read_package(root + AGENT_DIR + "/registry/projects.yaml", PROJECT)["sha256"]
        L.package_matches(root + APP_DIR, pin)
        steps = plan(rec, ts, root)          # re-reads the credential file: same refusal path
    except (L.PrecheckError, ValueError, OSError, TypeError, AttributeError) as e:
        print(red.text(f"run-client-audit: refused: {e}"), file=sys.stderr); return emit("refused", "precheck", 2)
    except Exception as e:
        if not a.json:
            raise
        return unexpected(e)
    if a.dry_run:
        for key, argv_, env in steps:
            shown = ["<script>" if len(x) > 200 else x for x in argv_]
            say(f"would run [{step_name(argv_)}] timeout={TIMEOUTS[key]}s: {' '.join(shown)}"
                f" env={sorted(k for k in env if k != 'PATH')}")
        return emit("ok", None, 0)
    state = {"results": [], "reason": None, "vault_path": None}
    try:
        with L.AuditLock(root + LOCK):
            rc = _run(steps, rec, ts, root, runner, say, state)
    except L.PrecheckError as e:
        print(f"run-client-audit: {e}", file=sys.stderr); return emit("busy", "busy", 3)
    except SystemExit as e:         # SIGTERM (_on_sigterm): cleanup has run; keep the one-JSON-line contract
        if e.code != 128 + signal.SIGTERM:
            raise
        print("run-client-audit: failed: terminated (SIGTERM)", file=sys.stderr)
        emit("failed", "internal", e.code, state["results"])
        raise
    except (OSError, ValueError, TypeError, AttributeError) as e:          # Ruling 6 (+ M12)
        say(f"run-client-audit: failed: {type(e).__name__}: {e}")
        return emit("failed", "internal", 1, state["results"])
    except Exception as e:          # _run's finally (transient removal, proxy stop) has already run
        if not a.json:
            raise
        return unexpected(e, state["results"])
    return emit("ok" if rc == 0 else "failed", state["reason"], rc, state["results"], state["vault_path"])


def _run(steps, rec, ts, root, runner, say, state):
    """state (main's) gets results as they happen, the failing class as "reason", and the vault path."""
    slug = rec["slug"]
    data = root + AUDIT_DATA + "/" + slug
    kw = ({"uid": os.geteuid(), "gid": os.getegid()} if DATA_UID is None
          else {"uid": DATA_UID, "gid": DATA_GID})
    L.reset_dir(data, **kw)
    for parent in (REPORTS, DRAFT_OUT):               # last run's reports/draft never leak into this one
        L.reset_dir(root + parent + "/" + slug, **kw)
    logs = root + AUDIT_LOGS + "/" + slug              # root-created, so rmtree is safe; 0711 so
    L.reset_dir(logs, uid=os.geteuid(), gid=os.getegid(), mode=0o711)   # 10000 reaches snapshot.stdout
    results = state["results"]
    try:
        for i, (key, argv_, env) in enumerate(steps):
            name = step_name(argv_)
            if key == "snapshot":                                   # collection just finished
                bad = L.error_files(data)
                if bad:
                    state["reason"] = "collect"
                    say(f"run-client-audit: collector errors, no draft: {bad}"); return _summary(results, 1, say)
                if L.json_count(data) == 0:
                    state["reason"] = "collect"
                    say("run-client-audit: collectors wrote no data, no draft"); return _summary(results, 1, say)
            if key == "vault-write":                  # isolation check BEFORE anything reaches the vault
                named = L.others_named(read_transient(root, slug, ts), slug, list(L.V.load_registry(root + REGISTRY)))
                if named:
                    results.append(("isolation", 1, 0.0))
                    state["reason"] = "isolation"
                    say(f"run-client-audit: ASSERTION FAIL — the draft names other clients: {named}; not written to the vault")
                    return _summary(results, 1, say)
            stem = os.path.join(logs, name.replace(":", "-"))
            t0 = time.monotonic()
            with open_log(stem + ".stdout") as out, open_log(stem + ".stderr") as err:
                if key == "snapshot" and DATA_UID is not None:   # vault-write (as 10000) reads it
                    os.fchown(out.fileno(), DATA_UID, DATA_GID)
                rc = runner(argv_, env, TIMEOUTS[key], out, err)
            results.append((name, rc, round(time.monotonic() - t0, 1)))
            if rc != 0:
                state["reason"] = step_class(name)
                say(f"run-client-audit: step {name} failed (rc {rc}); see {stem}.stderr")
                return _summary(results, 1, say)
        vault_draft = f"{VAULTS}/{slug}/audits/{ts}-audit.md"
        if not vault_draft_is_file(root, slug, ts):   # uid 10000 can write the vault tree
            state["reason"] = "vault-write"
            say("run-client-audit: vault-write reported success but the vault draft is missing")
            return _summary(results, 1, say)
        state["vault_path"] = vault_draft
        say(f"run-client-audit: draft -> {vault_draft}  (data collected {ts} UTC)")
        return _summary(results, 0, say)
    finally:                        # the transient draft never outlives the run (I3); the proxy stops
        try:
            remove_transient(root, slug, ts)
        finally:                    # even if the removal raises, the proxy must not outlive the run
            stop_proxy(root, logs, say)


def _summary(results, rc, say):
    for name, r, secs in results:
        say(f"  {name:<28} rc={r:<4} {secs}s")
    return rc


if __name__ == "__main__":
    signal.signal(signal.SIGTERM, _on_sigterm)      # the real entrypoint only; tests call main()
    sys.exit(main())
