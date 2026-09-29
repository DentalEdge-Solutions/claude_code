#!/usr/bin/env python3
"""Security-review evidence collector — BOX side (spec 2026-09-28 §4.2, §5).

  sudo python3 bin/collect-review-evidence.py                    > bundle-box.json
  sudo python3 bin/collect-review-evidence.py --fingerprint-only
  sudo python3 bin/collect-review-evidence.py --credentials-only

READ-ONLY. It observes and reports; it never judges — CHECKLIST.md says what each item
should show, and the independent reviewer compares. Three rules, each tested:
  * nothing printed carries a credential value, a client slug or a customer id;
  * an item it cannot run is `could-not-check`, never silently healthy (F17);
  * if it cannot load the redaction list (clients.json) it prints nothing and exits 2.
"""
import argparse, grp, json, os, pwd, re, stat, subprocess, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import changeset_lib as C
import package_lib as PK
import review_lib as R

AGENT_DIR = "/opt/hermes-agent"
CHECKOUT = "/opt/projects/claude_code"
GOV = "/var/lib/hermes/governance"
SPOOL = "/var/lib/hermes/spool"
UNITS = ("hermes-broker.service", "hermes-docker-proxy.service")
# One entry per app mounted into the executor: the host side of docker-compose.yml's
# HERMES_ADS_REPO_DIR bind (BRING-UP Phase 2). Add a line when an app is added.
APP_HOST_DIRS = {"claude_google_ads": "/opt/projects/claude-google-ads"}
GATEWAY_FILTER = "label=com.docker.compose.service=hermes-agent"
GATEWAY_PROBE_PATHS = ("/opt/governance", "/var/lib/hermes/governance",
                       "/projects/claude_google_ads/.env", "/opt/hermes-agent/.env.gaw",
                       "/opt/hermes-agent/.env.ga")
GATEWAY_CONTROL_PATH = "/opt/registry/projects.yaml"
SWEEP_NAMES = (".env*", "*.ga", "*.gaw", ".git-credentials", "hosts.yml", "credentials.json",
               "application_default_credentials.json", "id_rsa", "id_ecdsa", "id_ed25519")
HISTORY_FILES = (".bash_history", ".zsh_history", ".python_history")
# Moved into review_lib.py (final-review Group A4) so both the collector and
# review_lib.looks_like_credential_text share one definition. Kept as an alias here —
# the collector's own _count_cred_text still reads it under this name.
CRED_TEXT_RE = R.CRED_TEXT_RE
# Real filesystems that do not hold operator-placed credential material: pseudo/virtual
# mounts, plus the two container-runtime mounts (overlay, squashfs) a Docker/snap host
# always has and that are not places an operator would drop a credential file (D2.1,
# final-review A2). Anything else not swept by `find / -xdev` is reported so the
# reviewer can judge it explicitly, rather than the sweep silently missing it.
PSEUDO_FSTYPES = {"proc", "sysfs", "cgroup", "cgroup2", "devpts", "mqueue", "debugfs", "tracefs",
                  "securityfs", "pstore", "bpf", "configfs", "fusectl", "hugetlbfs", "autofs",
                  "binfmt_misc", "nsfs", "overlay", "squashfs"}
CODE_PATHS = ("infra/hermes-agent/bin", "infra/hermes-agent/deploy", "infra/hermes-agent/registry",
              "infra/hermes-agent/docker-compose.yml", "infra/hermes-agent/Dockerfile")
CHECKLIST = CHECKOUT + "/infra/hermes-agent/deploy/security-review/CHECKLIST.md"


def _run_real(argv, timeout=60):
    try:
        p = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
        return p.returncode, p.stdout, p.stderr
    except FileNotFoundError:
        return 127, "", f"{argv[0]}: not found"
    except subprocess.TimeoutExpired:
        return 124, "", f"{argv[0]}: timed out"


class Host:
    """Everything a probe touches, injectable for tests: the file root and the runner."""
    def __init__(self, root="/", run=None):
        self.root, self._run = root, run or _run_real

    def path(self, p):
        return os.path.join(self.root, p.lstrip("/"))

    def run(self, argv, timeout=60):
        return self._run(argv, timeout)


class CouldNotCheck(Exception):
    pass


def _ok(host, argv):
    rc, out, err = host.run(argv)
    if rc != 0:
        raise CouldNotCheck(f"{argv[0]} exited {rc}: {(err or out).strip()[:200]}")
    return out


def _owner(uid):
    try:
        return pwd.getpwuid(uid).pw_name
    except KeyError:
        return str(uid)


def _group(gid):
    try:
        return grp.getgrgid(gid).gr_name
    except KeyError:
        return str(gid)


def _stat(host, p):
    st = os.lstat(host.path(p))
    return {"owner": _owner(st.st_uid), "group": _group(st.st_gid),
            "mode": oct(stat.S_IMODE(st.st_mode)), "size": st.st_size}


def context(host):
    """Loaded once per run. Raises ValueError when the redaction list cannot load."""
    return {"redactor": R.Redactor.from_clients_json(host.path(GOV + "/registry/clients.json"))}


# ---------------------------------------------------------------- D1 host exposure
def d1_1(host, ctx):
    # -tulnH: TCP AND UDP (Important #3 — a UDP-only listener was invisible to -tlnH).
    # With both protocols requested, ss prints the Netid column: protocol at 0, local
    # address at 4. Prefix the listener with its protocol so tcp/udp on the same port
    # are two distinct entries, not one that silently shadows the other.
    out = _ok(host, ["ss", "-tulnH"])
    listeners = set()
    for line in out.splitlines():
        cols = line.split()
        if len(cols) > 4:
            listeners.add(f"{cols[0]} {cols[4]}")
    return {"listeners": sorted(listeners)}


def d1_2(host, ctx):
    return {"ufw": _ok(host, ["ufw", "status", "verbose"]).splitlines()}


def d1_3(host, ctx):
    keys = ("port", "permitrootlogin", "passwordauthentication", "kbdinteractiveauthentication",
            "pubkeyauthentication", "allowusers", "authenticationmethods")
    got = {}
    for line in _ok(host, ["sshd", "-T"]).splitlines():
        k, _, v = line.partition(" ")
        if k in keys:
            got[k] = v
    return got


def d1_4(host, ctx):
    rc, out, _ = host.run(["systemctl", "is-active", "fail2ban", "unattended-upgrades"])
    states = out.split()
    if len(states) != 2:
        raise CouldNotCheck("systemctl gave no answer")
    return {"fail2ban": states[0], "unattended-upgrades": states[1]}


def d1_5(host, ctx):
    shells = []
    with open(host.path("/etc/passwd")) as f:
        for line in f:
            parts = line.strip().split(":")
            if len(parts) == 7 and not parts[6].endswith(("nologin", "false", "sync")):
                shells.append({"user": parts[0], "shell": parts[6]})
    sudo = {}
    for g in ("sudo", "admin", "wheel"):
        members = _getent_group_members(host, g)
        if members is not None:
            sudo[g] = members
    sd = host.path("/etc/sudoers.d")
    return {"login_shells": shells, "sudo_groups": sudo,
            "sudoers_d": sorted(os.listdir(sd)) if os.path.isdir(sd) else []}


def _getent_group_members(host, group):
    """None means the group does not exist (getent's documented rc 2) — a real, observed
    answer, not a failure. Any other non-zero (including 127, missing binary) is
    could-not-check: we did not learn whether the group exists."""
    rc, out, _ = host.run(["getent", "group", group])
    if rc == 0:
        return [m for m in out.strip().split(":")[-1].split(",") if m]
    if rc == 2:
        return None
    raise CouldNotCheck(f"getent group {group} exited {rc}")


def d1_6(host, ctx):
    members = _getent_group_members(host, "docker")
    return {"docker_group_members": members if members is not None else []}


# ---------------------------------------------------------------- D2 credential inventory
def _sweep(host):
    argv = ["find", "/", "-xdev", "-type", "f", "("]
    for i, n in enumerate(SWEEP_NAMES):
        argv += (["-o"] if i else []) + ["-name", n]
    argv += [")"]
    rc, out, err = host.run(argv, timeout=600)
    # ANY non-zero exit is could-not-check (Important #1/#2, final-review A1) — an
    # unreadable subdirectory (find's rc 1) can hide exactly the file we're looking
    # for, so "rc 1 with some output" is no longer treated as a clean sweep. The
    # message never carries stderr TEXT, only its shape: the rc and how many lines it
    # had, so a path fragment in a permission-denied line cannot leak into the report.
    if rc != 0:
        raise CouldNotCheck(f"find exited {rc} ({len(err.splitlines())} stderr lines)")
    return sorted(set(line for line in out.splitlines() if line))


def _not_swept(host):
    """Mounts `_sweep`'s `find / -xdev` does NOT cross, other than real pseudo/virtual
    filesystems (final-review A2). Returns a sorted list of targets, or the literal
    string could-not-check if `findmnt` itself could not be read — the D2.1 item
    itself stays observed either way; the reviewer judges."""
    rc, out, _ = host.run(["findmnt", "-rn", "-o", "TARGET,FSTYPE"])
    if rc != 0:
        return R.COULD_NOT_CHECK
    not_swept = []
    for line in out.splitlines():
        cols = line.split()
        if len(cols) < 2:
            continue
        target, fstype = cols[0], cols[1]
        if target == "/" or fstype in PSEUDO_FSTYPES:
            continue
        not_swept.append(target)
    return sorted(set(not_swept))


def _shared_sweep(host, ctx):
    """One `find` per run (final-review A3): `d2_1` and `installed_credentials` must
    see the same candidate list, and must not each pay for (or each fail at) their own
    system-wide sweep. The result — the list, or the CouldNotCheck itself — is cached
    on ctx so a second caller in the same run gets it back without re-running `find`."""
    if "sweep" not in ctx:
        try:
            ctx["sweep"] = _sweep(host)
        except CouldNotCheck as e:
            ctx["sweep"] = e
    cached = ctx["sweep"]
    if isinstance(cached, CouldNotCheck):
        raise cached
    return cached


def installed_credentials(host, sweep=None):
    """(infos, secrets, unparsed, unreadable). `sweep` lets a caller that already paid
    for one system-wide sweep (e.g. collect_with_secrets, via _shared_sweep) hand it
    in rather than triggering a second `find` (final-review A3); omitted, this runs
    its own — the public signature callers already use is unchanged."""
    infos, secrets, unparsed, unreadable = [], [], [], []
    for p in (sweep if sweep is not None else _sweep(host)):
        if p.endswith(".example"):
            continue
        try:
            info, s = R.parse_credential_file(host.path(p))
        except OSError:
            unreadable.append(p)
            continue
        if info["refresh_token_sha12"] is None:
            try:
                with open(host.path(p), encoding="utf-8", errors="replace") as f:
                    text = f.read()
            except OSError:
                unreadable.append(p)
                continue
            if R.looks_like_credential_text(text):
                unparsed.append(p)
            continue                                        # not a Google Ads credential
        info["path"] = p
        infos.append(info); secrets += s
    return infos, secrets, unparsed, unreadable


def d2_1(host, ctx):
    rows = []
    for p in _shared_sweep(host, ctx):
        is_example = p.endswith(".example")
        row = {"path": p, "kind": "example" if is_example else "candidate"}
        try:
            row.update(_stat(host, p))
            if not is_example:
                info, s = R.parse_credential_file(host.path(p))
                ctx.setdefault("secrets", []).extend(s)
                if info["refresh_token_sha12"]:
                    row["credential"] = {k: info[k] for k in ("role", "refresh_token_sha12", "client_id_sha12")}
                else:
                    with open(host.path(p), encoding="utf-8", errors="replace") as f:
                        text = f.read()
                    if R.looks_like_credential_text(text):
                        row["kind"] = "unparsed"
        except OSError as e:
            row["error"] = type(e).__name__
            if not is_example:
                row["kind"] = "unreadable"
        rows.append(row)
    return {"files": rows, "not_swept": _not_swept(host)}


def _count_cred_text(text, secrets):
    return {"pattern_hits": len(CRED_TEXT_RE.findall(text)),
            "known_secret_hits": sum(text.count(s) for s in secrets if len(s) >= 8)}


def d2_2(host, ctx):
    homes = ["/root"] + ["/home/" + h for h in (sorted(os.listdir(host.path("/home")))
                                                if os.path.isdir(host.path("/home")) else [])]
    out = {}
    for home in homes:
        for name in HISTORY_FILES:
            p = f"{home}/{name}"
            if os.path.isfile(host.path(p)):
                with open(host.path(p), errors="replace") as f:
                    out[p] = _count_cred_text(f.read(), ctx.get("secrets", []))
    return {"histories": out}


def d2_3(host, ctx):
    return {"journal": _count_cred_text(_ok(host, ["journalctl", "-o", "cat", "--no-pager"]), ctx.get("secrets", []))}


# ---------------------------------------------------------------- D4 isolation boundaries
def d4_1(host, ctx):
    gw = _ok(host, ["docker", "ps", "-q", "--no-trunc", "--filter", GATEWAY_FILTER]).strip()
    if len(gw) != 64:
        raise CouldNotCheck("gateway container not running — isolation cannot be observed")
    script = ('for p in "$@"; do if [ -e "$p" ]; then if [ -r "$p" ]; then '
              'echo "$p readable $(wc -c < "$p" 2>/dev/null || echo dir)"; else echo "$p unreadable"; fi; '
              'else echo "$p absent"; fi; done')
    out = _ok(host, ["docker", "exec", gw, "sh", "-c", script, "sh", *GATEWAY_PROBE_PATHS, GATEWAY_CONTROL_PATH])
    env = _ok(host, ["docker", "exec", gw, "env"])
    return {"paths": out.splitlines(),
            "google_ads_env_names": sorted(l.split("=", 1)[0] for l in env.splitlines() if l.startswith("GOOGLE_ADS_"))}


def d4_2(host, ctx):
    active = host.run(["systemctl", "is-active", "hermes-docker-proxy"])[1].strip()
    execstart = _ok(host, ["systemctl", "show", "hermes-docker-proxy", "-p", "ExecStart"])
    return {"active": active, "execstart_sha256": PK.sha256_bytes(execstart.encode())}


def d4_3(host, ctx):
    out = {}
    for u in UNITS:
        inst, repo = host.path("/etc/systemd/system/" + u), host.path(CHECKOUT + "/infra/hermes-agent/deploy/" + u)
        out[u] = {"installed": PK.sha256_file(inst) if os.path.isfile(inst) else None,
                  "repo": PK.sha256_file(repo) if os.path.isfile(repo) else None}
    return out


def d4_4(host, ctx):
    rc, out, err = host.run(["runuser", "-u", "hermes-broker", "--", "python3", AGENT_DIR + "/bin/init-host-layout.py",
                             "--check", "--store-root", GOV, "--spool-root", SPOOL])
    return {"rc": rc, "output": (out + err).splitlines()[-40:]}


# ---------------------------------------------------------------- D5 governance store
def d5_1(host, ctx):
    rc, out, err = host.run(["runuser", "-u", "hermes-broker", "--", "python3",
                             AGENT_DIR + "/bin/preflight-governance-access.py", "--root", GOV])
    return {"rc": rc, "output": (out + err).splitlines()[-40:]}


def d5_2(host, ctx):
    logs = sorted(n for n in os.listdir(host.path(GOV + "/log")) if n.endswith(".jsonl"))
    sealed = 0
    for n in logs:
        rc, out, _ = host.run(["lsattr", GOV + "/log/" + n])
        if rc == 0 and "a" in out.split()[0]:
            sealed += 1
    return {"logs": len(logs), "sealed": sealed}


def d5_3(host, ctx):
    return {"kill_switch_present": os.path.lexists(host.path(GOV + "/control/mutation-enabled"))}


def d5_4(host, ctx):
    with open(host.path(GOV + "/registry/clients.json")) as f:
        clients = json.load(f).get("clients", {})
    by_status = {}
    for rec in clients.values():
        by_status[rec.get("status", "?")] = by_status.get(rec.get("status", "?"), 0) + 1
    return {"clients": len(clients), "by_status": by_status,
            "dormant_pilots": sum(1 for r in clients.values() if r.get("mutation_target") == "dormant_pilot")}


# ---------------------------------------------------------------- D6 app packages
def d6_1(host, ctx):
    projects = host.path(CHECKOUT + "/infra/hermes-agent/registry/projects.yaml")
    out = {}
    for project, d in APP_HOST_DIRS.items():
        row = {"placeholder": os.path.exists(host.path(d + "/PLACEHOLDER")),
               "git_dir": os.path.exists(host.path(d + "/.git"))}
        try:
            pin = C.read_package(projects, project)
            row["pin"] = pin and {"commit": pin["commit"], "sha256": pin["sha256"]}
        except ValueError as e:
            row["pin_error"] = str(e)
        mpath = host.path(d + "/" + PK.MANIFEST_NAME)
        if os.path.isfile(mpath):
            with open(mpath, "rb") as f:
                raw = f.read()
            m = PK.load_manifest(raw)
            bad = [e["path"] for e in m["files"]
                   if not os.path.isfile(host.path(d + "/" + e["path"]))
                   or PK.sha256_file(host.path(d + "/" + e["path"])) != e["sha256"]]
            extra = []
            for root, _, names in os.walk(host.path(d)):
                for n in names:
                    rel = os.path.relpath(os.path.join(root, n), host.path(d))
                    if rel not in {e["path"] for e in m["files"]} | {PK.MANIFEST_NAME, ".env"}:
                        extra.append(rel)
            row.update(installed_sha256=PK.sha256_bytes(raw), commit=m["commit"],
                       files=len(m["files"]), mismatched=bad, extra=sorted(extra))
        else:
            row["installed_sha256"] = None
        out[project] = row
    return out


def d6_2(host, ctx):
    rc, out, err = host.run(["find", "/root", "/home", "-xdev", "(", "-name", ".git-credentials", "-o",
                             "-path", "*/.config/gh/hosts.yml", "-o", "-name", "id_rsa", "-o",
                             "-name", "id_ecdsa", "-o", "-name", "id_ed25519", ")"])
    if rc != 0:                                             # final-review A1 — see _sweep
        raise CouldNotCheck(f"find exited {rc} ({len(err.splitlines())} stderr lines)")
    return {"git_or_ssh_private_credentials": sorted(l for l in out.splitlines() if l)}


# ---------------------------------------------------------------- D7 client data
def d7_1(host, ctx):
    vaults = host.path(AGENT_DIR + "/data/vaults")
    vault_rows = []
    if os.path.isdir(vaults):
        for n in sorted(os.listdir(vaults)):
            vault_rows.append(_stat(host, AGENT_DIR + "/data/vaults/" + n))
    records = host.path(GOV + "/records")
    backups = sorted(n for n in os.listdir(host.path("/root")) if n.startswith("live-gate-")) \
        if os.path.isdir(host.path("/root")) else []
    return {"vaults": vault_rows,
            "records": sum(len(fs) for _, _, fs in os.walk(records)) if os.path.isdir(records) else 0,
            "root_backups": [{"dir": b, "files": len(os.listdir(host.path("/root/" + b)))} for b in backups]}


PROBES = {"D1.1": d1_1, "D1.2": d1_2, "D1.3": d1_3, "D1.4": d1_4, "D1.5": d1_5, "D1.6": d1_6,
          "D2.1": d2_1, "D2.2": d2_2, "D2.3": d2_3,
          "D4.1": d4_1, "D4.2": d4_2, "D4.3": d4_3, "D4.4": d4_4,
          "D5.1": d5_1, "D5.2": d5_2, "D5.3": d5_3, "D5.4": d5_4,
          "D6.1": d6_1, "D6.2": d6_2, "D7.1": d7_1}


# ---------------------------------------------------------------- fingerprint (§5.1)
def _component(fn):
    try:
        return fn()
    except (CouldNotCheck, OSError, ValueError) as e:
        return {R.COULD_NOT_CHECK: type(e).__name__}


def box_fingerprint(host, ctx):
    def clients():
        with open(host.path(GOV + "/registry/clients.json"), "rb") as f:
            return PK.sha256_bytes(f.read())

    def packages():
        out = {}
        for project, d in APP_HOST_DIRS.items():
            p = host.path(d + "/" + PK.MANIFEST_NAME)
            if os.path.isfile(p):
                with open(p, "rb") as f:
                    raw = f.read()
                out[project] = {"sha256": PK.sha256_bytes(raw), "commit": PK.load_manifest(raw)["commit"]}
            else:
                out[project] = None
        return out

    def code():
        base = ["git", "-c", f"safe.directory={CHECKOUT}", "-C", CHECKOUT]
        trees = {p: _ok(host, base + ["rev-parse", f"HEAD:{p}"]).strip() for p in CODE_PATHS}
        dirty = _ok(host, base + ["status", "--porcelain", "--", *CODE_PATHS]).strip()
        return {"trees": trees, "dirty": bool(dirty)}

    def entry_points():
        # Important #3: fold in the firewall RULESET itself, not just the listener and
        # ufw-frontend views above — nft first, iptables-save as the fallback on a host
        # without nftables. If neither can be read, raise so the existing _component()
        # wrapper marks this whole component could-not-check, which correctly marks
        # the fingerprint incomplete (final-review B2).
        #
        # `-s` ("stateless") drops nft's live packet/byte counters at the source so the
        # dump is not volatile by construction; the fallback and the result are still run
        # through normalize_ruleset() because iptables-save has no such flag and Docker
        # rewrites its own chains regardless of which tool produced the dump.
        rc, out, _ = host.run(["nft", "-s", "list", "ruleset"])
        kind = "nft"
        if rc != 0:
            rc, out, _ = host.run(["iptables-save"])
            kind = "iptables"
            if rc != 0:
                raise CouldNotCheck("nft list ruleset and iptables-save both failed")
        return {"listeners": d1_1(host, ctx)["listeners"],
                "ufw": _ok(host, ["ufw", "status", "verbose"]).splitlines(),
                "sshd": sorted(_ok(host, ["sshd", "-T"]).splitlines()),
                "firewall_ruleset_sha256": PK.sha256_bytes(R.normalize_ruleset(out, kind).encode())}

    def checklist():
        with open(host.path(CHECKLIST)) as f:
            for line in f:
                m = re.match(r"^version:\s*(\S+)", line)
                if m:
                    return m.group(1)
        raise ValueError("no version line")

    return R.fingerprint({"clients": _component(clients), "packages": _component(packages),
                          "code": _component(code), "entry_points": _component(entry_points),
                          "checklist": _component(checklist)})


# ---------------------------------------------------------------- assembly
def collect_with_secrets(host):
    """The bundle (redacted) and every credential value seen, for assert_no_secret."""
    ctx = context(host)
    items = {}
    for iid, fn in PROBES.items():
        try:
            items[iid] = {"status": R.OBSERVED, "data": fn(host, ctx)}
        except (CouldNotCheck, OSError, ValueError, KeyError, IndexError) as e:
            items[iid] = {"status": R.COULD_NOT_CHECK, "reason": f"{type(e).__name__}: {e}"}
    try:
        sweep = _shared_sweep(host, ctx)                   # A3: reuse D2.1's sweep, don't re-run find
        infos, secrets, _unparsed, _unreadable = installed_credentials(host, sweep=sweep)
        creds = R.credential_set(infos)
    except CouldNotCheck as e:
        secrets, creds = [], {R.COULD_NOT_CHECK: str(e)}
    bundle = {"schema": 1, "kind": "box", "items": items,
              "fingerprint": box_fingerprint(host, ctx), "credentials": creds}
    return ctx["redactor"].obj(bundle), ctx.get("secrets", []) + secrets


def collect(host):
    return collect_with_secrets(host)[0]


def main(argv=None, host=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--fingerprint-only", action="store_true")
    g.add_argument("--credentials-only", action="store_true")
    a = ap.parse_args(argv)
    host = host or Host()
    try:
        ctx = context(host)
    except ValueError as e:
        print(f"collect-review-evidence: {e} — refusing to print anything I cannot redact", file=sys.stderr)
        return 2
    rc = 0
    if a.fingerprint_only:
        out, secrets = box_fingerprint(host, ctx), []
        if not out["complete"]:                             # E3: still print it, but flag it
            rc = 2
    elif a.credentials_only:
        try:
            infos, secrets, unparsed, unreadable = installed_credentials(host)
        except CouldNotCheck as e:
            print(f"collect-review-evidence: {e} — refusing to certify the installed set",
                  file=sys.stderr)
            return 2
        if unparsed or unreadable:
            print(f"collect-review-evidence: {len(unparsed)} unparsed and {len(unreadable)} "
                  "unreadable credential-shaped file(s) found — refusing to certify the "
                  "installed set", file=sys.stderr)
            return 2
        out = R.credential_set(infos)
    else:
        out, secrets = collect_with_secrets(host)
    text = json.dumps(ctx["redactor"].obj(out), indent=2, sort_keys=True)
    R.assert_no_secret(text, secrets)
    print(text)
    return rc


if __name__ == "__main__":
    sys.exit(main())
