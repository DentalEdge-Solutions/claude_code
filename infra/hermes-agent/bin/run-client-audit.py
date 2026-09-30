#!/usr/bin/env python3
"""One client's Google Ads trend-audit DRAFT on the box (spec 2026-09-29 ads-audits-on-the-box).

  sudo run-client-audit <client> [--dry-run]

Pre-checks, then: collect (one-shot ads-collector) -> snapshot (host) -> readers (one-shot
ads-reader) -> draft (claude -p in the gateway, as run-trend-audit.sh) -> vault-write -> the
check that the draft names no other client. Stops at the first failure. Exit: 0 draft
written, 1 a step failed, 2 a pre-check refused, 3 another audit is running.
Nothing shown carries a customer id or credential value; each step's stdout and stderr go to
/var/lib/hermes/audit-logs/<client>/<step>.{stdout,stderr} (root 0600; snapshot.stdout is handed
to uid 10000 for vault-write). The logs are OUTSIDE the tree the collector mounts rw, and every
file there is created O_EXCL|O_NOFOLLOW: root never follows a container-planted symlink."""
import argparse, datetime, json, os, re, stat, subprocess, sys, time
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
LOCK = "/run/lock/hermes-client-audit.lock"
PROJECT = "claude_google_ads"
TS_FMT = "%Y-%m-%d_%H-%M-%S"   # file names; the snapshot gets the same instant in ISO (M8)
COLLECTORS = ("audit_discovery", "negatives_audit", "audit_assets_rsa", "assess_supplemental")
READERS = ("account_overview", "audit_search_terms", "audit_analyze")
TIMEOUTS = {"collect": 900, "snapshot": 120, "read": 300, "draft": 1200, "vault-write": 120}
CRED_NAMES = ("GOOGLE_ADS_DEVELOPER_TOKEN", "GOOGLE_ADS_CLIENT_ID", "GOOGLE_ADS_CLIENT_SECRET",
              "GOOGLE_ADS_REFRESH_TOKEN", "GOOGLE_ADS_LOGIN_CUSTOMER_ID", "GOOGLE_ADS_CUSTOMER_ID")
OWNER_UID = 0                 # the credential file's owner; tests override
DATA_UID = DATA_GID = 10000   # the containers' uid; tests set None to skip chown
PIN_OVERRIDE = None           # tests only
# vault-write runs on the HOST but writes files the gateway (uid 10000) must read next month
# (trend mode): run it AS that uid, or the vault fills with root-owned files. The snapshot runs
# as that uid too: it reads files the collector container controls (F2). Tests set [].
RUN_AS_DATA_UID = ["setpriv", "--reuid=10000", "--regid=10000", "--clear-groups"]

# Verbatim from run-trend-audit.sh (spec §2 step 5): the analyst, its model and its limits.
# One change (I2): `timeout -k 30 1150` stops claude INSIDE the container before the host's
# 1200 s timeout, which can only kill the `docker compose exec` client; -k 30 sends SIGKILL if
# claude ignores SIGTERM, still inside 1200 s (F3).
DRAFT_SCRIPT = r'''
  set -eu
  skill="/opt/data/skills/claude-code-ads-analyst/SKILL.md"
  vault="/opt/data/vaults/$CLIENT"; reports="/opt/data/reports/$PROJECT"
  ls "$reports"/*.md >/dev/null 2>&1 || { echo "no reports for $PROJECT" >&2; exit 1; }
  mkdir -p "/opt/data/audits/$PROJECT"
  out="/opt/data/audits/$PROJECT/$TS-audit.md"
  timeout -k 30 1150 claude -p "Read and follow $skill EXACTLY, INCLUDING its Trend mode. Produce the Google Ads audit DRAFT for project $PROJECT. Fresh scrubbed reports: $reports/. THIS client'\''s prior history (read for trend deltas): $vault/metrics/, $vault/audits/, $vault/timeline.md (may be empty on the first run = establish baseline). SOP/benchmark docs: /projects/$PROJECT/. Read ONLY within $vault, $reports, and /projects/$PROJECT. Do NOT attempt ExitPlanMode and do NOT narrate your tools or environment; BEGIN your response with the DRAFT banner and output ONLY the deliverable markdown." \
    --allowedTools "Read,Grep,Glob" --permission-mode plan --model claude-opus-4-8 > "$out"
  echo "$out"
'''


def step_name(argv):
    if "ads-collector" in argv:
        return "collect:" + os.path.basename(argv[-1])[:-3]
    if "ads-reader" in argv:
        return "read:" + argv[argv.index("--report") + 1]
    if "exec" in argv:
        return "draft"
    return "snapshot" if any(a.endswith("ads-metrics-snapshot.py") for a in argv) else "vault-write"
    # (snapshot and vault-write argvs may start with RUN_AS_DATA_UID; neither test looks at argv[0])


def open_log(path):
    """A NEW 0600 log file; refuses (OSError) anything already there, a symlink included."""
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    return os.fdopen(fd, "w")


# Everything below data/ is the gateway's (uid 10000): any component can be a planted symlink.
# Root reaches it only through L.open_dir_below from the trusted checkout, then acts on names
# relative to that fd (F1). data/ itself cannot be swapped: its parent is the root-owned checkout.
def _data_dir(root, *parts):
    return L.open_dir_below(root + AGENT_DIR, ("data",) + parts)


def clear_reports(root):
    """Remove last run's *.md from data/reports/<project>. unlink never follows the final name."""
    fd = _data_dir(root, "reports", PROJECT)
    if fd is None:
        return
    try:
        for f in os.listdir(fd):
            if f.endswith(".md"):
                os.unlink(f, dir_fd=fd)
    finally:
        os.close(fd)


def read_transient(root, ts):
    fd = _data_dir(root, "audits", PROJECT)
    if fd is None:
        raise FileNotFoundError("the transient draft is missing")
    try:
        ffd = os.open(f"{ts}-audit.md", os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
    finally:
        os.close(fd)
    with os.fdopen(ffd, encoding="utf-8", errors="replace") as f:
        if not stat.S_ISREG(os.fstat(ffd).st_mode):          # a planted FIFO must not hang root
            raise L.UnsafePathError("the transient draft is not a regular file")
        return f.read()


def remove_transient(root, ts):
    fd = _data_dir(root, "audits", PROJECT)
    if fd is None:
        return
    try:
        os.unlink(f"{ts}-audit.md", dir_fd=fd)
    except FileNotFoundError:
        pass
    finally:
        os.close(fd)


def vault_draft_is_file(root, slug, ts):
    fd = _data_dir(root, "vaults", slug, "audits")
    if fd is None:
        return False
    try:
        return stat.S_ISREG(os.stat(f"{ts}-audit.md", dir_fd=fd, follow_symlinks=False).st_mode)
    except FileNotFoundError:
        return False
    finally:
        os.close(fd)


def _quiet(argv):
    try:
        return subprocess.run(argv, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=60).returncode
    except (subprocess.TimeoutExpired, OSError) as e:
        return type(e).__name__


def real_runner(argv, env, timeout, out, err, cleanup=None):
    """out/err are the open log files (open_log); nothing is re-opened by path. A timeout kills
    only the `docker compose` client, so a named `run` container is removed explicitly (I2):
    it must not keep writing into the next client's reports."""
    try:
        return subprocess.run(argv, env=env, stdout=out, stderr=err, timeout=timeout).returncode
    except subprocess.TimeoutExpired:
        err.write(f"\n[run-client-audit] timed out after {timeout}s\n")
        if "--name" in argv:
            name = argv[argv.index("--name") + 1]
            rc = (cleanup or _quiet)(["docker", "rm", "-f", name])
            err.write(f"[run-client-audit] docker rm -f {name}: rc {rc}\n")
        err.flush()
        return 124


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
            "GOOGLE_ADS_CUSTOMER_ID": cid, "HERMES_AUDIT_DATA_DIR": data}
    eflags = [x for n in CRED_NAMES for x in ("-e", n)]
    run = lambda step: (_compose(root) + ["run", "--rm", "--no-deps", "-T", "--name", f"hermes-audit-{ts}-{step}"]
                        + eflags)                     # named, so a timeout can remove it (I2)
    steps = [("collect", run(f"collect-{c}") + ["ads-collector", f"code/{c}.py"], cred) for c in COLLECTORS]
    # The snapshot reads collector-controlled audit-data/<slug>/*.json: never as root (F2). Its
    # stdout is still the root-created, fchown'd snapshot.stdout fd.
    steps.append(("snapshot", RUN_AS_DATA_UID + ["python3", root + AGENT_DIR + "/bin/ads-metrics-snapshot.py",
                               "--audit-data", root + data, "--customer", cid, "--collected-at", collected_at], base))
    steps += [("read", run(f"read-{r}") + ["ads-reader", "--report", r, "--project", PROJECT], cred)
              for r in READERS]
    # Non-secret, validated values inline (M9): slug (eligible_client), PROJECT (constant), ts (_iso).
    steps.append(("draft", _compose(root) + ["exec", "-e", f"PROJECT={PROJECT}", "-e", f"CLIENT={slug}",
                                             "-e", f"TS={ts}", "-T", "hermes-agent", "sh", "-lc", DRAFT_SCRIPT],
                  base))
    steps.append(("vault-write", RUN_AS_DATA_UID + ["python3", root + AGENT_DIR + "/bin/vault-write.py", "--client", slug,
                                  "--audit-file", root + f"{AGENT_DIR}/data/audits/{PROJECT}/{ts}-audit.md",
                                  "--metrics-file", root + AUDIT_LOGS + "/" + slug + "/snapshot.stdout", "--ts", ts,
                                  "--registry", root + REGISTRY],
                  {**base, "VAULT_ROOT": root + AGENT_DIR + "/data/vaults", "TS": ts}))
    return steps


def main(argv=None, runner=None, root="/", now=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("client")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)
    root = root.rstrip("/")
    runner = runner or real_runner
    ts = now or datetime.datetime.now(datetime.timezone.utc).strftime(TS_FMT)
    try:
        rec = L.eligible_client(a.client, root + REGISTRY)
    except (L.PrecheckError, ValueError, OSError, TypeError, AttributeError) as e:   # M12: malformed entry
        print(f"run-client-audit: refused: {e}", file=sys.stderr); return 2
    red = R.Redactor([], [rec["customer_id"]])
    say = lambda s: print(red.text(s))
    try:
        L.check_secret_file(root + CRED, uid=OWNER_UID, mode=0o400)
        if L.anthropic_key_state(root + AGENT_DIR + "/.env") != "real":
            raise L.PrecheckError("the gateway .env has no real Anthropic key")
        pin = PIN_OVERRIDE or C.read_package(root + AGENT_DIR + "/registry/projects.yaml", PROJECT)["sha256"]
        L.package_matches(root + APP_DIR, pin)
        steps = plan(rec, ts, root)          # re-reads the credential file: same refusal path
    except (L.PrecheckError, ValueError, OSError, TypeError, AttributeError) as e:
        print(red.text(f"run-client-audit: refused: {e}"), file=sys.stderr); return 2
    if a.dry_run:
        for key, argv_, env in steps:
            shown = ["<script>" if len(x) > 200 else x for x in argv_]
            say(f"would run [{step_name(argv_)}] timeout={TIMEOUTS[key]}s: {' '.join(shown)}"
                f" env={sorted(k for k in env if k != 'PATH')}")
        return 0
    try:
        with L.AuditLock(root + LOCK):
            return _run(steps, rec, ts, root, runner, say)
    except L.PrecheckError as e:
        print(f"run-client-audit: {e}", file=sys.stderr); return 3
    except (OSError, ValueError, TypeError, AttributeError) as e:          # Ruling 6 (+ M12)
        say(f"run-client-audit: failed: {type(e).__name__}: {e}"); return 1


def _run(steps, rec, ts, root, runner, say):
    slug = rec["slug"]
    data = root + AUDIT_DATA + "/" + slug
    kw = ({"uid": os.geteuid(), "gid": os.getegid()} if DATA_UID is None
          else {"uid": DATA_UID, "gid": DATA_GID})
    L.reset_dir(data, **kw)
    logs = root + AUDIT_LOGS + "/" + slug              # root-created, so rmtree is safe; 0711 so
    L.reset_dir(logs, uid=os.geteuid(), gid=os.getegid(), mode=0o711)   # 10000 reaches snapshot.stdout
    results = []
    try:
        for i, (key, argv_, env) in enumerate(steps):
            name = step_name(argv_)
            if key == "snapshot":                                   # collection just finished
                bad = L.error_files(data)
                if bad:
                    say(f"run-client-audit: collector errors, no draft: {bad}"); return _summary(results, 1, say)
                if L.json_count(data) == 0:
                    say("run-client-audit: collectors wrote no data, no draft"); return _summary(results, 1, say)
            if key == "read" and name.endswith(READERS[0]):          # before the first reader
                clear_reports(root)       # a symlinked reports dir raises UnsafePathError: rc 1
            if key == "vault-write":                  # isolation check BEFORE anything reaches the vault
                named = L.others_named(read_transient(root, ts), slug, list(L.V.load_registry(root + REGISTRY)))
                if named:
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
                say(f"run-client-audit: step {name} failed (rc {rc}); see {stem}.stderr")
                return _summary(results, 1, say)
        vault_draft = f"{AGENT_DIR}/data/vaults/{slug}/audits/{ts}-audit.md"
        if not vault_draft_is_file(root, slug, ts):   # the gateway can write the vault tree
            say("run-client-audit: vault-write reported success but the vault draft is missing")
            return _summary(results, 1, say)
        say(f"run-client-audit: draft -> {vault_draft}  (data collected {ts} UTC)")
        return _summary(results, 0, say)
    finally:                        # the transient draft never outlives the run (I3)
        remove_transient(root, ts)


def _summary(results, rc, say):
    for name, r, secs in results:
        say(f"  {name:<28} rc={r:<4} {secs}s")
    return rc


if __name__ == "__main__":
    sys.exit(main())
