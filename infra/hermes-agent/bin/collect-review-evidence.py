#!/usr/bin/env python3
"""Security-review evidence collector — BOX side (spec 2026-09-28 §4.2, §5).

  sudo python3 bin/collect-review-evidence.py                    > bundle-box.json
  sudo python3 bin/collect-review-evidence.py --fingerprint-only
  sudo python3 bin/collect-review-evidence.py --credentials-only
  sudo python3 bin/collect-review-evidence.py --fp-key-tty --last-pass-execstart <64 hex> --last-pass-collected-at <UTC time>

It observes and reports; it never judges — CHECKLIST.md says what each item should show,
and the independent reviewer compares. It changes nothing a review looks at, but the full
bundle is NOT read-only: D10.1 and D10.2 run `run-client-audit --probe-env` and
`--probe-egress`, which take the audit lock, start the audit containers (and the egress
proxy), create and remove `/var/lib/hermes/probe`, and make one outbound CONNECT to
`api.anthropic.com` through the proxy. `--fingerprint-only` and `--credentials-only` run no
probe. Three rules, each tested:
  * nothing printed carries a credential value (Google, Anthropic, OpenRouter, the API server key or the dashboard password),
    a client slug or a customer id;
  * an item it cannot run is `could-not-check`, never silently healthy (F17);
  * if it cannot load the redaction list (clients.json) it prints nothing and exits 2.
"""
import argparse, ast, base64, calendar, datetime, fnmatch, getpass, grp, json, os, pwd, re, shlex, stat, subprocess, sys, tempfile, threading, time
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import app_lib as A
import changeset_lib as C
import client_audit_lib as CAL
import gateway_listeners as GL
import host_layout as HL
import mcp_config
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
GATEWAY_FILTER = GL.GATEWAY_FILTER
GATEWAY_PROBE_PATHS = ("/opt/governance", "/var/lib/hermes/governance",
                       "/projects/claude_google_ads/.env", "/opt/hermes-agent/.env.gaw",
                       "/opt/hermes-agent/.env.ga",
                       "/etc/hermes/.env" + ".ga",
                       "/var/lib/hermes/vaults", "/var/lib/hermes/reports", "/var/lib/hermes/draft-out",
                       "/var/lib/hermes/audit-data", "/var/lib/hermes/app-state",
                       "/etc/hermes/.env.anthropic", "/opt/data/vaults", "/opt/data/reports",
                       "/opt/data/home/.claude/settings.json")
GATEWAY_CONTROL_PATH = "/opt/registry/projects.yaml"
SWEEP_NAMES = (".env*", "*.ga", "*.gaw", ".git-credentials", "hosts.yml", "credentials.json",
               "application_default_credentials.json", "id_rsa", "id_ecdsa", "id_ed25519")
HISTORY_FILES = (".bash_history", ".zsh_history", ".sh_history", ".ash_history", ".python_history",
                 ".psql_history", ".mysql_history", ".sqlite_history", ".node_repl_history",
                 ".rediscli_history", ".lesshst")
# Non-Google secret files the box is meant to hold (README credential table). A sweep hit
# at one of these paths is `authorised-other`; any other non-empty, non-Google hit is
# `unlisted`, which the reviewer must see explained (review #3, not-on-checklist #3).
GATEWAY_ENV_FILE = CHECKOUT + "/infra/hermes-agent/.env"
# Hermes's own secrets file in HERMES_HOME (/opt/data/.env in the container): from v0.21.5 its
# start-up seeds it from the bundled template and appends a generated API_SERVER_KEY. Hermes loads
# it with override=True, so a credential placed here overrides the gateway's own .env.
HERMES_HOME_ENV_FILE = CHECKOUT + "/infra/hermes-agent/data/.env"
AUTHORISED_OTHER = {GATEWAY_ENV_FILE: "gateway-env",
                    "/etc/hermes/.env.anthropic": "anthropic-key",
                    HERMES_HOME_ENV_FILE: "hermes-home-env"}
# The secret values each authorised non-Google file may hold, as (env name, label). D2.1 names the
# labels a file holds (`secrets_held`), EVERY value a name is given joins the known secrets the
# leak checks look for, and a label with one value is a row of the authorised credential set
# (`credentials`, --credentials-only). Same files as AUTHORISED_OTHER (tested).
OTHER_SECRET_NAMES = {
    "/etc/hermes/.env.anthropic": (("ANTHROPIC_API_KEY", "anthropic-key"),),
    GATEWAY_ENV_FILE: (("OPENROUTER_API_KEY", "openrouter-key"),
                       ("HERMES_DASHBOARD_BASIC_AUTH_PASSWORD", "dashboard-password"),
                       # The preferred form since Hermes v0.21.5: no plaintext at rest (F47). It is
                       # written single-quoted, because Compose interpolates `$` (F52).
                       ("HERMES_DASHBOARD_BASIC_AUTH_PASSWORD_HASH", "dashboard-password-hash"),
                       # Signs the dashboard's session tokens, so a restart does not sign the
                       # operator out. Random (install-env-secret.py generate).
                       ("HERMES_DASHBOARD_BASIC_AUTH_SECRET", "dashboard-session-secret")),
    HERMES_HOME_ENV_FILE: (("API_SERVER_KEY", "api-server-key"),)}
# D2.1 `credential_shaped_names` (the Hermes home file only): an assignment NAME holding one of
# these is credential-shaped. Names only, never a value; the file's own key is expected there.
CREDENTIAL_NAME_PARTS = ("KEY", "TOKEN", "SECRET", "PASSWORD", "PASSWD", "CREDENTIAL", "AUTH")
HERMES_HOME_OWN_NAMES = ("API_SERVER_KEY",)
# Listed, never fingerprinted: a short hash of a value a person may have chosen can be guessed offline.
# The password's scrypt hash is a verifier of that same value, so it gets no fingerprint either.
UNFINGERPRINTED = ("dashboard-password", "dashboard-password-hash")
# What D4.1 says when there is no one gateway container to look into. Fixed text.
NO_GATEWAY = "gateway container not running — isolation cannot be observed"
# D4.1 `secret_env`: the only four things said about a secret in the running gateway's environment.
MATCHES_FILE, DIFFERS_FROM_FILE, UNSET = "matches-file", "differs-from-file", "unset"
# What _other_secrets reports about a file it could still read. Fixed text: never a value or a path.
UNDECODABLE = "undecodable bytes"
# An assignment as an env-file reader such as Docker Compose also takes it: indented, `export`
# and any blanks, blanks before the `=`. Rewritten to the bare `NAME=` that CAL.env_values reads,
# so a line the gateway would use is never one this collector skips.
_ENV_ASSIGN_RE = re.compile(r"^[ \t]*(?:export[ \t]+)?([A-Za-z_][A-Za-z0-9_]*)[ \t]*=")
_LINE_END_RE = re.compile(r"\r\n|\r|\n")
# Writable in-memory filesystems `find / -xdev` never crosses: the collector sweeps them
# itself, by name and by content (review #3 §5 — the manual sweep went stale).
MEMORY_FSTYPES = {"tmpfs", "ramfs"}
MEMORY_READ_LIMIT = 1 << 20
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
# The chat-triggered app (Option B spec 2026-09-30 §3, §6, §8.1): gateway MCP client -> broker
# (unprivileged) -> runner (root) -> run-client-audit.
APP = "ads-audit"
APP_USER = "hermes-app-" + APP
APP_UNITS = ("hermes-app-broker@.service", "hermes-app-runner@.service", "hermes-app-runner@.path")
APP_RESULTS = "/var/lib/hermes/spool/apps/" + APP + "/results"
# The probes start real containers: --probe-env's worst case is about 480 s, --probe-egress's 240 s.
PROBE_TIMEOUT = 600
# On a timeout the child gets SIGTERM and this long to clean up before SIGKILL: run-client-audit
# removes its probe containers and throwaway dirs on TERM (each cleanup command is bounded there).
TERM_GRACE = 90
# Spec §6's hardening list, plus what the unit's environment holds (the declared map gives the
# broker and the runner no credential; a drop-in could add one without changing the unit file).
ENV_PROPS = ("Environment", "EnvironmentFiles")
BROKER_PROPS = ("User", "NoNewPrivileges", "CapabilityBoundingSet", "PrivateNetwork", "PrivateTmp",
                "ProtectSystem", "ProtectHome", "ReadWritePaths", "UMask", "ActiveState") + ENV_PROPS
# What the broker's journal lines may say (hermes-app-broker.py _say): a result's status, or
# `queued` / `dropped`, which never become a result.
JOURNAL_STATUSES = A.STATUSES + ("queued", "dropped")
JOURNAL_REASONS = A.BROKER_REASONS + A.COMMAND_REASONS + ("expired", "-")
_BROKER_LINE = "hermes-app-broker[" + APP + "]: "
_SAY_RE = re.compile(r"request=\S+ op=\S+ client=\S+ status=(\S+) reason=(\S+)")
_NOTE_RE = re.compile(r"(warning|error): ")
WITHHELD = "<withheld>"
# D10.6: the gateway's live config (in ./data, which the gateway's uid owns: read as hostile) and
# the template it is installed from. Only their `mcp_servers:` blocks are compared, as parsed
# values (mcp_config): the gateway rewrites its file, so the layout is not the template's.
MCP_BOX_CONFIG = AGENT_DIR + "/data/config.yaml"
MCP_REPO_CONFIG = CHECKOUT + "/infra/hermes-agent/config.yaml.example"
MCP_CONFIG_CAP = 64 * 1024
MCP_LIST_LINES, MCP_LIST_WIDTH = 40, 200
_ENV_NAME_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
# systemd prints `argv[]=<the command line> ; ignore_errors=...` inside the ExecStart value.
_ARGV_RES = (re.compile(r"argv\[\]=.* ; ignore_errors="), re.compile(r"argv\[\]=.*? ; "))


def _run_real(argv, timeout=60, errors="strict"):
    try:
        # The lossy read names UTF-8, so "one replacement character for each byte, or cut-short
        # sequence of bytes, that is not valid UTF-8" holds under any locale; the strict default
        # keeps the locale's own encoding, as before.
        decoding = {} if errors == "strict" else {"encoding": "utf-8"}
        p = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, errors=errors, **decoding)
    except FileNotFoundError:
        return 127, "", f"{argv[0]}: not found"
    with p:                                     # on every path: pipes closed (unread), child reaped
        try:
            out, err = p.communicate(timeout=timeout)
            return p.returncode, out, err
        except subprocess.TimeoutExpired:
            p.terminate()                       # not kill(): the child's `finally` must get to run
            try:
                p.communicate(timeout=TERM_GRACE)
            except subprocess.TimeoutExpired:
                p.kill()
                p.wait()                        # the child only: a grandchild holding a pipe must not hang us
            return 124, "", f"{argv[0]}: timed out"
        except BaseException:                   # as subprocess.run: never leave the child behind
            p.kill()
            raise


class _RealStream:
    """One command's stdout line by line, never held whole: `rc` and `err` are set once the lines
    have ended. Each line is decoded as UTF-8 with one replacement character for each byte, or
    cut-short sequence of bytes, that is not valid. On a timeout the child gets SIGTERM, the lines
    end and rc is 124. stderr goes to an unnamed temporary file, so a child that writes a lot of
    it cannot block on a full pipe."""
    ERR_CAP = 65536
    MAX_LINE = 64 * 1024 * 1024
    TERM_GRACE = TERM_GRACE

    def __init__(self, argv, timeout):
        self._argv, self._timeout, self.rc, self.err = argv, timeout, None, ""

    def __iter__(self):
        errf = tempfile.TemporaryFile()
        try:
            p = subprocess.Popen(self._argv, stdout=subprocess.PIPE, stderr=errf)
        except FileNotFoundError:
            errf.close()
            self.rc, self.err = 127, f"{self._argv[0]}: not found"
            return
        except BaseException:
            errf.close()
            raise
        timed_out = threading.Event()

        def stop():
            timed_out.set()
            p.terminate()                       # not kill(): as _run_real
            try:
                p.wait(timeout=self.TERM_GRACE)
            except subprocess.TimeoutExpired:
                p.kill()
        timer = threading.Timer(self._timeout, stop)
        timer.start()
        try:
            while True:
                raw = p.stdout.readline(self.MAX_LINE)      # a piece without a newline is yielded as it is
                if not raw:
                    break
                yield raw.decode("utf-8", errors="replace")
            try:
                p.wait(timeout=self.TERM_GRACE)
            except subprocess.TimeoutExpired:
                p.kill()
                p.wait()
        finally:
            timer.cancel()
            if p.poll() is None:                # the caller stopped early, or raised: never leave the child behind
                p.kill()
                p.wait()
            p.stdout.close()
            size = errf.seek(0, os.SEEK_END)
            errf.seek(0)
            err = errf.read(self.ERR_CAP).decode("utf-8", errors="replace")
            if size > self.ERR_CAP:
                err += " [more on stderr]"
            errf.close()
        self.rc, self.err = (124, f"{self._argv[0]}: timed out") if timed_out.is_set() else (p.returncode, err)


class _TextStream:
    """A fake runner's (rc, out, err) behind the same interface."""
    def __init__(self, result):
        self.rc, self._out, self.err = result

    def __iter__(self):
        lines = self._out.split("\n")          # "\n" only, as the real stream (splitlines also splits on \r, U+2028...)
        return iter([l + "\n" for l in lines[:-1]] + ([lines[-1]] if lines[-1] else []))


class Host:
    """Everything a probe touches, injectable for tests: the file root and the runner."""
    def __init__(self, root="/", run=None):
        self.root, self._run, self._real = root, run or _run_real, run is None

    def path(self, p):
        return os.path.join(self.root, p.lstrip("/"))

    def run(self, argv, timeout=60):
        return self._run(argv, timeout)

    def run_lossy(self, argv, timeout=60):
        """The same single command and limit as run(), for a read whose bytes need not be valid
        text (the journal): a byte that is not UTF-8 becomes U+FFFD instead of ending the read. A
        host built with a fake runner calls it unchanged."""
        return _run_real(argv, timeout, errors="replace") if self._real else self._run(argv, timeout)

    def stream(self, argv, timeout=60):
        """The same single command and limit as run_lossy(), read line by line instead of held
        whole (the journal with every field is about 183 million characters at 35 days, measured 2026-10-13). A
        host built with a fake runner streams that runner's text."""
        return _RealStream(argv, timeout) if self._real else _TextStream(self._run(argv, timeout))


class CouldNotCheck(Exception):
    pass


def _ok(host, argv, timeout=60):
    rc, out, err = host.run(argv, timeout)
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


def _tty_key():
    try:
        return getpass.getpass("review fingerprint key (hidden, from `pbcopy < ~/.config/hermes-review/fp.key`): ")
    except (EOFError, OSError):
        return ""


def context(host, fp_key=None):
    """Loaded once per run. Raises ValueError when the redaction list cannot load."""
    return {"redactor": R.Redactor.from_clients_json(host.path(GOV + "/registry/clients.json"), fp_key=fp_key)}


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


# D1.7: the sshd settings that say where a key, a certificate or a forward may come from.
SSHD_KEY_SOURCES = ("authorizedkeysfile", "authorizedkeyscommand", "authorizedprincipalsfile",
                    "trustedusercakeys", "allowtcpforwarding", "allowstreamlocalforwarding",
                    "gatewayports", "permittunnel")
# D1.7: the limited key's `permitlisten="127.0.0.1:1"` refuses a remote forward only while an
# unprivileged account cannot bind port 1 (measured: with this setting at 0 the listener opens).
UNPRIVILEGED_PORT_START = "/proc/sys/net/ipv4/ip_unprivileged_port_start"
_KEY_TYPE_RE = re.compile(r"(ssh-(rsa|dss|ed25519)|ecdsa-sha2-nistp(256|384|521)"
                          r"|sk-(ssh-ed25519|ecdsa-sha2-nistp256)@openssh\.com)(-cert-v01@openssh\.com)?")
_KEY_BODY_RE = re.compile(r"[A-Za-z0-9+/]{16,}={0,3}")
_OPTION_NAME_RE = re.compile(r"[A-Za-z0-9-]+")
# The only option VALUES printed: a plain program path, and a loopback target. Any other value
# (an address in from=, a command line with arguments, an environment assignment) is withheld.
_SHOWN_OPTION_RES = {"command": re.compile(r"[A-Za-z0-9_./-]+"),
                     "permitopen": re.compile(r"(127\.0\.0\.1|localhost|\[::1\]):([0-9]{1,5}|\*)"),
                     "permitlisten": re.compile(r"((127\.0\.0\.1|localhost|\[::1\]):)?([0-9]{1,5}|\*)")}


def _split_unquoted(text, seps):
    """(parts, unbalanced): `text` split on any character of `seps` outside double quotes, as
    sshd's option scan reads a line: a backslash escapes only a double quote (the pair is kept
    and never toggles quoting, inside or outside quotes); any other backslash is an ordinary
    character. Empty parts are dropped. `unbalanced` is True when a quote is never closed."""
    parts, cur, quoted, i = [], [], False, 0
    while i < len(text):
        c = text[i]
        if c == "\\" and text[i + 1:i + 2] == '"':
            cur.append(text[i:i + 2])
            i += 2
            continue
        if c == '"':
            quoted = not quoted
        if c in seps and not quoted:
            if cur:
                parts.append("".join(cur))
            cur = []
        else:
            cur.append(c)
        i += 1
    if cur:
        parts.append("".join(cur))
    return parts, quoted


def _shown_option(opt):
    name, eq, value = opt.partition("=")
    if not _OPTION_NAME_RE.fullmatch(name):
        return WITHHELD
    if not eq:
        return name
    inner = value[1:-1] if len(value) >= 2 and value[0] == value[-1] == '"' else value
    rx = _SHOWN_OPTION_RES.get(name.lower())
    return opt if rx and rx.fullmatch(inner) else f"{name}={WITHHELD}"


# What sshd's base64 reader skips inside a key body besides the space and tab that end it
# (measured against sshd 9.6p1: docs/evaluations/2026-10-10-journal-retention-35-days.md).
_KEY_BODY_SKIPPED = str.maketrans("", "", "\r\n\x0b\x0c")


def _key_fields(text):
    """(type, body bytes) when `text` starts with a key type and a key body, as sshd's key reader
    takes them: two fields, each ended by a space or a tab. Whatever follows is the comment; it
    is never looked at (a quote in it means nothing to sshd). None otherwise."""
    parts = re.split(r"[ \t]+", text, maxsplit=2)
    if len(parts) < 2 or not _KEY_TYPE_RE.fullmatch(parts[0]):
        return None
    body = parts[1].translate(_KEY_BODY_SKIPPED)
    if not _KEY_BODY_RE.fullmatch(body):
        return None
    try:
        return parts[0], base64.b64decode(body, validate=True)
    except ValueError:
        return None


def _key_row(line):
    """One authorized_keys line as its key type, its options and a short fingerprint of the key
    body, or None when it is not a key line. Read as sshd reads it: a key first, or the options
    (up to the first space or tab outside double quotes) and then a key. The body and the comment
    are never returned."""
    text = line.strip(" \t")
    got, options = _key_fields(text), []
    if got is None:
        i, quoted = 0, False
        while i < len(text) and (quoted or text[i] not in " \t"):
            if text[i] == "\\" and text[i + 1:i + 2] == '"':
                i += 1                                  # sshd skips both characters
            elif text[i] == '"':
                quoted = not quoted
            i += 1
        if quoted:                                      # the options never end: sshd finds no key
            return None
        got = _key_fields(text[i:].lstrip(" \t"))
        if got is None:
            return None
        options = _split_unquoted(text[:i], ",")[0]
    return {"type": got[0], "options": sorted(_shown_option(o) for o in options),
            "sha12": PK.sha256_bytes(got[1])[:12]}


def _authorized_keys_paths(pattern, user, home):
    """The files sshd reads for one account, from its AuthorizedKeysFile value: `%h`, `%u` and `%%`
    expanded, a relative name taken under the home directory. Another token is could-not-check:
    a file this collector cannot name is a file it did not read."""
    out = []
    for pat in pattern.split():
        if pat == "none":
            continue
        p = pat.replace("%%", "\0").replace("%h", home).replace("%u", user)
        if "%" in p:
            raise CouldNotCheck("authorizedkeysfile holds a token this collector does not expand")
        p = p.replace("\0", "%")
        out.append(os.path.normpath(p if p.startswith("/") else os.path.join(home, p)))
    return out


AUTHORIZED_KEYS_READ_LIMIT = 1 << 20      # bytes; a larger key file is could-not-check, never a partial list


def _read_key_file(fd):
    """The lines of the open key file, or None when it is larger than the limit. sshd ends a line
    at a newline only (str.splitlines would also split on \\r, \\f and U+2028)."""
    with os.fdopen(fd, "rb") as f:
        data = f.read(AUTHORIZED_KEYS_READ_LIMIT + 1)
    if len(data) > AUTHORIZED_KEYS_READ_LIMIT:
        return None
    return data.decode("utf-8", errors="replace").split("\n")


def _authorized_keys_row(host, p, users):
    full = host.path(p)
    row = {"path": p, "users": sorted(users)}
    unread = {"keys": R.COULD_NOT_CHECK, "unparsed_lines": R.COULD_NOT_CHECK}
    fd = None
    try:                                    # one open, never through a link: what is read is what was examined
        fd = os.open(full, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
        st = os.fstat(fd)
    except OSError:
        if fd is not None:
            os.close(fd)
        try:
            st = os.lstat(full)             # a link, or a file that cannot be opened: describe it, read nothing
        except OSError:
            return {**row, "kind": R.COULD_NOT_CHECK, "owner": R.COULD_NOT_CHECK, "group": R.COULD_NOT_CHECK,
                    "mode": R.COULD_NOT_CHECK, **unread}
        fd = None
    kind = "file" if stat.S_ISREG(st.st_mode) else "symlink" if stat.S_ISLNK(st.st_mode) else "not-a-file"
    row.update(kind=kind, owner=_owner(st.st_uid), group=_group(st.st_gid), mode=oct(stat.S_IMODE(st.st_mode)))
    if fd is not None and (kind != "file" or st.st_size > AUTHORIZED_KEYS_READ_LIMIT):
        os.close(fd)
        fd = None
    if fd is None:
        return {**row, **unread}
    try:
        lines = _read_key_file(fd)
    except OSError:
        return {**row, **unread}
    if lines is None:
        return {**row, **unread}
    keys, unparsed = [], 0
    for line in lines:
        if not line.strip(" \t\r") or line.lstrip(" \t").startswith("#"):
            continue
        key = _key_row(line)
        if key is None:
            unparsed += 1
        else:
            keys.append(key)
    return {**row, "keys": keys, "unparsed_lines": unparsed}


def _unprivileged_port_start(host):
    """The first port an account without privileges may bind, as the kernel states it (a host's
    default is 1024). Read as bytes, a few at most: anything that is not one plain ASCII port
    number, with at most one line break after it, is could-not-check."""
    try:
        with open(host.path(UNPRIVILEGED_PORT_START), "rb") as f:
            raw = f.read(16)
    except OSError:
        return R.COULD_NOT_CHECK
    m = re.fullmatch(rb"(0|[1-9][0-9]{0,4})\n?", raw)
    if not m or int(m.group(1)) > 65535:
        return R.COULD_NOT_CHECK
    return int(m.group(1))


SSHD_CONFIG = "/etc/ssh/sshd_config"
SSHD_CONFIG_DIR = "/etc/ssh/sshd_config.d"
# The only spellings of the standard Include that are not counted as reaching elsewhere: the glob
# bare or in one pair of double quotes, after the bare keyword and blanks (measured on sshd 9.6p1:
# an `=`, a quoted blank, a control character or a second argument around it makes sshd read another
# path or pattern as well).
_SSHD_STANDARD_INCLUDE_RE = re.compile(
    r'[ \t]*(?i:include)[ \t]+(")?(?:/etc/ssh/sshd_config\.d/\*\.conf|sshd_config\.d/\*\.conf)(?(1)")[ \t\r]*',
    re.ASCII)                                       # the keyword folds ASCII letters only, as sshd's does


def _sshd_skipped(c):
    """A character the head scan skips: a blank or control character, a double quote or an `=`."""
    return c <= " " or c == "\x7f" or c in '"='


def _sshd_head(line):
    """(head, index): the first 7 characters of `line` that are not skipped, lower-cased, and the
    index just after the last one taken."""
    taken, i = [], 0
    while i < len(line) and len(taken) < 7:
        if not _sshd_skipped(line[i]):
            taken.append(line[i])
        i += 1
    return "".join(taken).lower(), i


def _sshd_match_lines(host):
    """(match_lines, include_elsewhere): the `Match` lines in the two places this collector reads
    (the main file and sshd_config.d/*.conf), and the `Include` lines there that name anything
    else than the standard glob. A `Match` block's settings are not read: its presence is what a
    reviewer must hear of. A file brought in from elsewhere is not read either, which is why it is
    counted. The count is a superset by construction. Match: a line is read by skipping every blank
    or control character, double quote and `=`, which is more than sshd's tokenizer drops before and
    inside a keyword (measured on sshd 9.6p1, docs/evaluations/2026-10-10-journal-retention-35-days.md);
    a head starting `match` is a Match line (sshd refuses a keyword it does not know, so counting
    `Matchmaker` falls only on a file it refuses). Include: the same head says it is an Include line,
    and it is "not elsewhere" only when the whole line is the standard glob in four forms (absolute
    or relative, bare or in one pair of double quotes) after the bare keyword in any ASCII letter case,
    with spaces or tabs before and between, and spaces, tabs or carriage returns after; every other
    spelling counts as elsewhere, an over-count. A place that cannot be read, is
    over the limit or holds a NUL byte (which may join two lines for sshd) makes both could-not-check:
    a count of 0 must mean 0 was found."""
    try:
        names = sorted(n for n in os.listdir(host.path(SSHD_CONFIG_DIR)) if n.endswith(".conf"))
    except FileNotFoundError:
        names = []
    except OSError:
        return R.COULD_NOT_CHECK, R.COULD_NOT_CHECK
    matches = elsewhere = 0
    for p in [SSHD_CONFIG] + [SSHD_CONFIG_DIR + "/" + n for n in names]:
        try:
            with open(host.path(p), "rb") as f:
                data = f.read(AUTHORIZED_KEYS_READ_LIMIT + 1)
        except OSError:
            return R.COULD_NOT_CHECK, R.COULD_NOT_CHECK
        if len(data) > AUTHORIZED_KEYS_READ_LIMIT:
            return R.COULD_NOT_CHECK, R.COULD_NOT_CHECK
        if b"\x00" in data:
            return R.COULD_NOT_CHECK, R.COULD_NOT_CHECK
        for line in data.decode("utf-8", errors="replace").split("\n"):
            head, end = _sshd_head(line)
            if head.startswith("match"):
                matches += 1
            elif head == "include":
                elsewhere += not _SSHD_STANDARD_INCLUDE_RE.fullmatch(line)
    return matches, elsewhere


# The title sshd 9.6p1 gives its listener process: "sshd: " + the command line it was started with +
# " [listener] N of M-K startups" (measured, docs/evaluations/2026-10-10-journal-retention-35-days.md,
# "How the running sshd was started"). Its children are titled by the closed set below, the only forms
# `ps -ww -C sshd -o args=` showed during and after logins on 9.6p1; every other line is unknown.
_SSHD_LISTENER_TITLE_RE = re.compile(r"sshd: (?P<args>\S.*) \[listener\] [0-9]+ of [0-9]+-[0-9]+ startups")
_SSHD_NAME = r"[A-Za-z0-9_][A-Za-z0-9_.$-]*"
_SSHD_CHILD_TITLE_RE = re.compile(
    r"sshd: \[(?:accepted|net|rexeced)\]"
    rf"|sshd: {_SSHD_NAME}(?: \[(?:net|priv)\]|@(?:notty|pts/[0-9]+))"
    r"|/usr/sbin/sshd -D -R|\[sshd\]|\[sshd\] <defunct>", re.ASCII)
_SSHD_BARE_NAME_RE = re.compile(rf"sshd: ({_SSHD_NAME})", re.ASCII)


def _account_names(host):
    """The account names in /etc/passwd, or None when the file cannot be read."""
    try:
        with open(host.path("/etc/passwd")) as f:
            return {line.split(":", 1)[0] for line in f.read().split("\n") if line and not line.startswith("#")}
    except (OSError, UnicodeDecodeError):
        return None


_SSHD_OPTIONS_WITH_ARGUMENT = "CEbcfghkopu"          # sshd's getopt string: `C:E:b:c:f:g:h:k:o:p:u:46DQRTdeiqrt`


def _sshd_daemon_options(host):
    """{"listeners", "config_file_options", "setting_options"}: how many sshd listener processes
    run and how many `-f` and `-o` options their command lines hold, read from `ps -ww -C sshd -o
    args=` (counts only: no path, option value or process id leaves here). `-ww` because procps
    applies COLUMNS even to a pipe and would cut a long title (measured). Every non-empty line is
    classified: a full-line listener title is counted; a full-line child title from the closed set
    above is ignored; ANY OTHER line (a title cut short, as a daemon started with a small
    environment gets, a process never retitled, a line a local account made, trailing blanks) makes
    all three could-not-check, because it may be a second daemon with options. The bare form
    `sshd: NAME` is ignored only when NAME is an account in /etc/passwd, because a daemon's own cut
    title can end that way (its last argument's last character) while a suffixed form cannot. Options are read as
    getopt does (`-f path`, `-fpath`, `-Df path`). The title joins the arguments with blanks and
    /proc/PID/cmdline holds that same one string (measured), so the original argument vector is not
    available: every word that starts with `-` is read as an option cluster and a word that does not
    (an option's value, a value holding a blank as two words) is skipped, never a reason to stop.
    A value that itself starts with `-` reads as an option: the counts can only be too high. `ps` finding
    no sshd (rc 1, no output at all) is 0 listeners; any other failure is could-not-check, never a
    healthy-looking value. Not seen: `ps -C sshd` lists by command name, so an OpenSSH daemon run
    from a binary with another name is not listed (the listening-port items would show it); any local
    account can add a line that looks like a listener or an unrecognised one, which makes the item
    CANNOT-VERIFY, never a pass. A daemon started through `ssh.socket` has the ordinary listener title
    once a first connection has started it (measured in a container, and read on the box on
    2026-10-11: record section 2); before that connection there is no sshd process: 0 listeners."""
    unknown = {k: R.COULD_NOT_CHECK for k in ("listeners", "config_file_options", "setting_options")}
    rc, out, err = host.run(["ps", "-ww", "-C", "sshd", "-o", "args="])
    if rc == 1 and not out and not err:
        return {"listeners": 0, "config_file_options": 0, "setting_options": 0}
    if rc != 0:
        return unknown
    listeners = config_files = settings = 0
    for line in out.split("\n"):
        if not line:
            continue
        m = _SSHD_LISTENER_TITLE_RE.fullmatch(line)
        if not m:
            if _SSHD_CHILD_TITLE_RE.fullmatch(line):
                continue
            bare = _SSHD_BARE_NAME_RE.fullmatch(line)
            if bare and bare.group(1) in (_account_names(host) or ()):
                continue
            return unknown
        listeners += 1
        for word in m.group("args").split()[1:]:      # the first word is the program
            if len(word) < 2 or word[0] != "-":
                continue                                # not an option word (a value, perhaps with a blank)
            for letter in word[1:]:                     # a cluster: letters up to the first that takes an argument
                if letter in _SSHD_OPTIONS_WITH_ARGUMENT:
                    config_files += letter == "f"
                    settings += letter == "o"
                    break
    return {"listeners": listeners, "config_file_options": config_files, "setting_options": settings}


def d1_7(host, ctx):
    """Every SSH key the box accepts, for EVERY account in /etc/passwd: an account with no login
    shell can still be used for a forward. Key types, options and short fingerprints only. The
    sshd settings are the global ones (`sshd -T`): a `Match` block's settings are not
    read here, only counted (`match_lines`); the fingerprint's entry_points component carries
    the whole of `sshd -T`. The kernel's
    net.ipv4.ip_unprivileged_port_start setting is read because the limited key's permitlisten
    depends on it. `sshd -T`, `match_lines` and `include_elsewhere` all read the default configuration;
    `daemon_options` says whether the running daemon uses it."""
    got = {}
    for line in _ok(host, ["sshd", "-T"]).splitlines():
        k, _, v = line.partition(" ")
        if k in SSHD_KEY_SOURCES:
            got[k] = v.strip()
    if "authorizedkeysfile" not in got:
        raise CouldNotCheck("sshd -T printed no authorizedkeysfile")
    users_of, accounts = {}, 0
    with open(host.path("/etc/passwd")) as f:
        for line in f:
            line = line.rstrip("\n")
            if not line.strip() or line.startswith("#"):
                continue
            parts = line.split(":")
            # Not measured (no container image here): whether the system's own account lookup
            # accepts a short line. A line this collector cannot read as an account may still be
            # one, and its key file would go unlisted, so the whole item is could-not-check.
            if len(parts) != 7:
                raise CouldNotCheck("an /etc/passwd line does not have seven fields")
            accounts += 1
            for p in _authorized_keys_paths(got["authorizedkeysfile"], parts[0], parts[5] or "/"):
                try:
                    os.lstat(host.path(p))
                except (FileNotFoundError, NotADirectoryError):
                    continue                # no such file: nothing accepts a key from it
                except OSError:
                    pass                    # cannot tell: keep the path, the row says so
                users_of.setdefault(p, set()).add(parts[0])
    match_lines, include_elsewhere = _sshd_match_lines(host)
    daemon_options = _sshd_daemon_options(host)
    return {"sshd": {k: got.get(k, R.COULD_NOT_CHECK) for k in SSHD_KEY_SOURCES},
            "accounts_checked": accounts,
            "unprivileged_port_start": _unprivileged_port_start(host),
            "match_lines": match_lines, "include_elsewhere": include_elsewhere,
            "daemon_options": daemon_options,
            "files": [_authorized_keys_row(host, p, users_of[p]) for p in sorted(users_of)]}


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


def _mounts(host, nsfs=None):
    """[(target, fstype)] for every mount `find / -xdev` does NOT cross, other than real
    pseudo/virtual filesystems (final-review A2), or None when `findmnt` cannot be read.
    `nsfs`, a set the caller passes, collects the targets of nsfs mounts (Docker namespace
    handles), which are pseudo and so never in the result: _memory_sweep classifies them."""
    rc, out, _ = host.run(["findmnt", "-rn", "-o", "TARGET,FSTYPE"])
    if rc != 0:
        return None
    mounts = set()
    for line in out.splitlines():
        cols = line.split()
        if len(cols) < 2 or cols[0] == "/":
            continue
        if cols[1] == "nsfs" and nsfs is not None:
            nsfs.add(cols[0])
        if cols[1] in PSEUDO_FSTYPES:
            continue
        mounts.add((cols[0], cols[1]))
    return sorted(mounts)


def _not_swept(host, mounts):
    """Targets the root sweep did not cross — a sorted list, or could-not-check. The D2.1
    item itself stays observed either way; the reviewer judges."""
    return R.COULD_NOT_CHECK if mounts is None else sorted({t for t, _ in mounts})


def _memory_sweep(host, mounts, nsfs=()):
    """Sweep the writable in-memory mounts the root sweep skips: a file whose NAME is
    credential-shaped (SWEEP_NAMES), or whose CONTENT looks like a Google Ads credential.
    Paths only, never content. Each mount is walked without crossing into another mount
    (it is walked on its own), regular files only, the first MEMORY_READ_LIMIT bytes."""
    if mounts is None:
        return R.COULD_NOT_CHECK
    targets = sorted(t for t, fs in mounts if fs in MEMORY_FSTYPES)
    ns = {t for t, fs in mounts if fs == "nsfs"} | set(nsfs)   # Docker namespace handles: classified, not read
    names, contents, unreadable, handles = set(), set(), set(), set()
    for m in targets:
        top = host.path(m)
        try:
            dev = os.lstat(top).st_dev
        except OSError:
            unreadable.add(m)
            continue
        def shown_of(full):
            return "/" + os.path.relpath(full, host.path("/"))

        def same_mount(full):
            # /run churns: a directory that vanishes between listing and lstat is skipped,
            # never allowed to fail the whole item.
            try:
                return os.lstat(full).st_dev == dev
            except OSError:
                return False

        # onerror: a directory walk cannot enter is REPORTED, never silently skipped.
        for root, dirs, files in os.walk(top, onerror=lambda e: unreadable.add(shown_of(e.filename))):
            dirs[:] = [d for d in dirs if same_mount(os.path.join(root, d))]
            for n in files:
                full = os.path.join(root, n)
                shown = shown_of(full)
                if shown in ns:
                    handles.add(shown)
                    continue
                try:
                    st = os.lstat(full)
                    if not stat.S_ISREG(st.st_mode):
                        continue
                    if any(fnmatch.fnmatch(n, pat) for pat in SWEEP_NAMES):
                        names.add(shown)
                    with open(full, encoding="utf-8", errors="replace") as f:
                        if R.looks_like_credential_text(f.read(MEMORY_READ_LIMIT)):
                            contents.add(shown)
                except OSError:
                    unreadable.add(shown)
    return {"mounts": targets, "name_hits": sorted(names), "content_hits": sorted(contents),
            "unreadable": sorted(unreadable), "namespace_handles": sorted(handles)}


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


def _read_env(host, p):
    """(text, problems): the file `p` read once, as bytes, decoded tolerantly, without a byte-order
    mark, every assignment rewritten to the bare `NAME=` (_ENV_ASSIGN_RE). `problems` is
    [UNDECODABLE] when a byte was not UTF-8, else []. Raises only what opening or reading raises."""
    with open(host.path(p), "rb") as f:
        text = f.read().decode("utf-8", errors="replace")
    problems = [UNDECODABLE] if "�" in text else []
    if text.startswith("﻿"):                           # a byte-order mark is not part of a name
        text = text[1:]
    text = "\n".join(_ENV_ASSIGN_RE.sub(r"\1=", line, count=1) for line in _LINE_END_RE.split(text))
    return text, problems


_BARE_ASSIGN_RE = re.compile(r"([A-Za-z_][A-Za-z0-9_]*)=")


def _credential_shaped_names(text):
    """The sorted, distinct assignment NAMES in _read_env's `text` that hold one of
    CREDENTIAL_NAME_PARTS, other than HERMES_HOME_OWN_NAMES. Names only: no value is looked at."""
    names = set()
    for line in text.split("\n"):
        m = _BARE_ASSIGN_RE.match(line)
        if m and m.group(1) not in HERMES_HOME_OWN_NAMES and \
                any(part in m.group(1).upper() for part in CREDENTIAL_NAME_PARTS):
            names.add(m.group(1))
    return sorted(names)


def _other_secrets(host, p, read=None):
    """(held, problems) for the authorised file `p`, read once, as bytes, and decoded tolerantly
    (as R.parse_credential_file reads the Google files): a damaged file never costs a value.
    `held` is [(label, value)] for every DISTINCT non-empty value of every name in
    OTHER_SECRET_NAMES[p], names in table order and values in file order: whichever line the
    file's real reader prefers, its value is here, in its bare form (no quotes, comment or
    surrounding whitespace). `problems` is fixed text only, empty for a healthy file: UNDECODABLE
    when a byte was not UTF-8, "duplicate <label>" when one name is given two different values.
    Raises only what opening or reading the file raises. `read`, when given, is _read_env's
    result for `p`, so a caller that also needs the file's names reads it once."""
    text, problems = read if read is not None else _read_env(host, p)
    problems = list(problems)
    held = []
    for name, label in OTHER_SECRET_NAMES[p]:
        values = list(dict.fromkeys(CAL.env_values(text, name)))
        held += [(label, v) for v in values]
        if len(values) > 1:
            problems.append(f"duplicate {label}")
    return held, problems


def _secret_forms(value):
    """The forms of a non-Google secret value to look for, the value itself first: also the value
    without surrounding whitespace and, when it holds a line break, each of its lines without
    theirs. A key that reached its reader with a blank or a line break around it (`NAME="<key> "`)
    is in a journal or in the gateway's own text as the bare key; the listing is split into lines
    before it is printed. Empty forms are dropped; a plain value is its only form."""
    forms = [value, value.strip()] + [line.strip() for line in value.splitlines()]
    return [f for f in dict.fromkeys(forms) if f]


def _seed(ctx, values):
    """Every form of every value joins ctx["secrets"], unless it is already there."""
    known = ctx.setdefault("secrets", [])
    for value in values:
        for form in _secret_forms(value):
            if form not in known:
                known.append(form)


def other_credentials(host):
    """(rows, secrets, failed) for the non-Google secrets installed. Each file is read on its own.
    One that is absent adds nothing (D2.1's pass rule names the missing row). One that cannot be
    opened or read adds "<file label>: <ExceptionClass>" to `failed`; one that was read but holds
    undecodable bytes, or two different values for one name, adds "<file label>: <problem>".
    Anything in `failed` makes the set could-not-check, never "none", and the rest still count.
    `secrets` gets EVERY value read, problem or not. `rows` gets one {label, sha12} row per label
    with exactly one value (sha12 null for an UNFINGERPRINTED one); a label with two has no row."""
    rows, secrets, failed = [], [], []
    for p in sorted(OTHER_SECRET_NAMES):
        try:
            held, problems = _other_secrets(host, p)
        except FileNotFoundError:
            continue
        except OSError as e:
            failed.append(f"{AUTHORISED_OTHER[p]}: {type(e).__name__}")
            continue
        failed += [f"{AUTHORISED_OTHER[p]}: {problem}" for problem in problems]
        secrets += [v for _, v in held]
        labels = [label for label, _ in held]
        rows += [{"label": label, "sha12": None if label in UNFINGERPRINTED else R.sha12(v)}
                 for label, v in held if labels.count(label) == 1]
    return sorted(rows, key=R.canon), secrets, failed


def gateway_secret_env(host):
    """(states, secrets): what the RUNNING gateway holds for each secret its `.env` may give it.
    The collector's own parse of that file and Docker Compose's can differ (a quoted value
    followed by text, an escape, `$`, `NAME: value`); the container's environment is what the
    gateway really uses, so it is asked, one `printenv <NAME>` per name and never through a shell.
    `states` is {label: state} for every label of the gateway file, in table order: MATCHES_FILE
    (the value is one _other_secrets read from the file for that label), DIFFERS_FROM_FILE (it is
    not, which includes a file that could not be read), UNSET (the name is not in the environment,
    or is empty) or R.COULD_NOT_CHECK (the answer could not be had). `secrets` is every non-empty
    value read, exactly as read, for the known-secret list (_seed adds its forms): never for printing.
    Nothing a `printenv` call writes, to stdout or to stderr, reaches a message: this never
    calls _ok, and it raises only CouldNotCheck(NO_GATEWAY), when there is no one container."""
    try:
        rc, out, _ = host.run(["docker", "ps", "-q", "--no-trunc", "--filter", GATEWAY_FILTER])
    except (OSError, ValueError):
        raise CouldNotCheck(NO_GATEWAY) from None
    gw = out.strip()
    if rc != 0 or len(gw) != 64:
        raise CouldNotCheck(NO_GATEWAY)
    try:
        held = _other_secrets(host, GATEWAY_ENV_FILE)[0]
    except OSError:
        held = []                                           # nothing read: no value can match
    states, secrets = {}, []
    for name, label in OTHER_SECRET_NAMES[GATEWAY_ENV_FILE]:
        try:
            rc, out, err = host.run(["docker", "exec", gw, "printenv", name])
        except (OSError, ValueError):                       # it could not be run, or its output is not
            states[label] = R.COULD_NOT_CHECK               # UTF-8 (the runner decodes strictly)
            continue
        if rc == 0:
            if not out:                                     # printenv ends even an empty value with a
                states[label] = R.COULD_NOT_CHECK           # newline: no output at all is not its answer
                continue
            value = out[:-1] if out.endswith("\n") else out  # ONE newline is printenv's; the rest is the value
            if not value:
                states[label] = UNSET
                continue
            states[label] = MATCHES_FILE if (label, value) in held else DIFFERS_FROM_FILE
            secrets.append(value)
        elif rc == 1 and not out and not err:
            states[label] = UNSET                           # printenv: not in the environment (it prints nothing)
        else:
            # Not measured, so never `unset`: a timeout, no printenv, a Docker error. `docker exec`
            # itself exits 1, with a message, for a container that has just stopped.
            states[label] = R.COULD_NOT_CHECK
    return states, secrets


def _gateway_secret_states(host, ctx):
    """gateway_secret_env, asked ONCE per run and kept on ctx: the states, or R.COULD_NOT_CHECK
    when there was no gateway to ask. Every value read joins ctx["secrets"], in each of its forms
    (_seed), so the leak checks and the output check look for what the gateway really holds."""
    if "secret_env" not in ctx:
        try:
            states, values = gateway_secret_env(host)
        except CouldNotCheck:
            ctx["secret_env"] = R.COULD_NOT_CHECK
        else:
            _seed(ctx, values)
            ctx["secret_env"] = states
    return ctx["secret_env"]


def d2_1(host, ctx):
    """Every sweep hit gets a kind: example, credential (a Google Ads credential), unparsed
    (credential-shaped but not parseable), empty, authorised-other (AUTHORISED_OTHER, with
    its label), unlisted (anything else non-empty), or unreadable (it could not be read, or it
    is an authorised file with undecodable bytes: `error` is then `undecodable`, and the row
    still names what the file holds)."""
    rows = []
    for p in _shared_sweep(host, ctx):
        is_example = p.endswith(".example")
        row = {"path": p, "kind": "example" if is_example else "unlisted"}
        try:
            row.update(_stat(host, p))
            if not is_example:
                info, s = R.parse_credential_file(host.path(p))
                ctx.setdefault("secrets", []).extend(s)
                if info["refresh_token_sha12"]:
                    row["kind"] = "credential"
                    row["credential"] = {k: info[k] for k in ("role", "refresh_token_sha12", "client_id_sha12")}
                else:
                    with open(host.path(p), encoding="utf-8", errors="replace") as f:
                        text = f.read()
                    if R.looks_like_credential_text(text):
                        row["kind"] = "unparsed"
                    elif row["size"] == 0:
                        row["kind"] = "empty"
                    elif p in AUTHORISED_OTHER:
                        row["kind"], row["label"] = "authorised-other", AUTHORISED_OTHER[p]
                        # Every value joins the known secrets, in each of its forms (unless
                        # collect_with_secrets already seeded it) before anything below can fail,
                        # whatever state the file is in; the row names which are held, never a value.
                        read = _read_env(host, p)
                        held, problems = _other_secrets(host, p, read)
                        _seed(ctx, [v for _, v in held])
                        if p == HERMES_HOME_ENV_FILE:
                            # A credential here would override the gateway's own environment.
                            row["credential_shaped_names"] = _credential_shaped_names(read[0])
                        row["secrets_held"] = list(dict.fromkeys(label for label, _ in held))
                        # Held but too short for the leak counters to search for (R._MIN_SECRET_LEN).
                        row["secrets_not_searchable"] = list(dict.fromkeys(
                            label for label, v in held if len(v) < R._MIN_SECRET_LEN))
                        if UNDECODABLE in problems:
                            # Not a file to state anything more about (a duplicated name alone
                            # leaves the row authorised-other: `credentials` reports it).
                            row["kind"], row["error"] = "unreadable", "undecodable"
                        elif p == "/etc/hermes/.env.anthropic":
                            row["anthropic_key_state"] = CAL.anthropic_key_state(host.path(p))
        except (OSError, ValueError) as e:                  # e.g. it cannot be opened: this row only
            row["error"] = type(e).__name__
            if not is_example:
                row["kind"] = "unreadable"
        rows.append(row)
    handles = set()
    mounts = _mounts(host, nsfs=handles)
    return {"files": rows, "not_swept": _not_swept(host, mounts),
            "memory_sweep": _memory_sweep(host, mounts, handles)}


def _count_cred_text(text, secrets):
    return {"pattern_hits": len(CRED_TEXT_RE.findall(text)),
            "known_secret_hits": sum(text.count(s) for s in set(secrets) if len(s) >= 8)}


def _homes(host):
    """/root, every /home/*, and every home directory /etc/passwd names — service
    accounts included (review #3 §8: two login accounts' histories were not enough)."""
    homes = {"/root"} | {"/home/" + h for h in (os.listdir(host.path("/home"))
                                               if os.path.isdir(host.path("/home")) else [])}
    try:
        with open(host.path("/etc/passwd")) as f:
            for line in f:
                cols = line.rstrip("\n").split(":")
                if len(cols) >= 6 and cols[5].startswith("/") and cols[5] != "/":
                    homes.add(cols[5])
    except OSError:
        pass
    return sorted(h for h in homes if os.path.isdir(host.path(h)))


def d2_2(host, ctx):
    out = {}
    for home in _homes(host):
        for name in HISTORY_FILES:
            p = f"{home}/{name}"
            if os.path.isfile(host.path(p)):
                with open(host.path(p), errors="replace") as f:
                    out[p] = _count_cred_text(f.read(), ctx.get("secrets", []))
    return {"histories": out}


# The search of the whole journal with every field measured 4 s at 7.9 days on the box (2026-10-13:
# 41,571 entries, 41.3 MB). Scaled to 35 days that is 18 s; times 10 for margin is 180 s; the limit
# is never under 300 s.
JOURNAL_SCAN_TIMEOUT = 300


def _not_root_on_a_real_host(host):
    """Run by anyone but root, journalctl shows only that user's own entries, with rc 0 and nothing
    on stderr (record R14, item 7). The real host (built with the real runner) refuses; a host
    built with a fake runner (tests) is not asked."""
    return host._real and os.geteuid() != 0


# Every stored field of every entry (finding F59: `-o cat` prints the message alone, and a token in
# a command line is stored in `_CMDLINE`). `--all`: without it a field over 4096 bytes prints as null.
# `-q`: as the box measurement was made; without it journalctl prints "-- No entries --" for a unit that never logged, which is not an entry.
JOURNAL_ALL_FIELDS = ["-o", "json", "--all", "--no-pager", "-q"]
# The customer-id count skips a field only when the journal service writes it itself, no program
# can set it, and it holds a number or an identifier by construction: a ten-digit id can match a
# long number there by chance (design 2026-10-13, from the box's 70 field names). The credential
# search skips nothing.
CID_SKIP_FIELDS = frozenset({
    "__CURSOR", "__REALTIME_TIMESTAMP", "__MONOTONIC_TIMESTAMP", "__SEQNUM", "__SEQNUM_ID",
    "_SOURCE_REALTIME_TIMESTAMP", "_SOURCE_MONOTONIC_TIMESTAMP",
    "_BOOT_ID", "_MACHINE_ID", "_STREAM_ID", "_SYSTEMD_INVOCATION_ID",
    "_PID", "_UID", "_GID", "_AUDIT_LOGINUID", "_AUDIT_SESSION", "_SYSTEMD_OWNER_UID"})
SEARCH_COUNTS = ("pattern_hits", "known_secret_hits", "credential_text_lines", "customer_id_lines",
                 "entries", "fields", "scanned_characters", "undecodable_characters")


def _byte_list(v):
    return isinstance(v, list) and all(isinstance(b, int) and not isinstance(b, bool) and 0 <= b <= 255 for b in v)


def _field_texts(value):
    """A journal field's value as the texts to search. systemd's JSON gives a string; a list of
    byte numbers for a value that is not text; a list of those two for a field set more than once.
    None for anything else (null: journalctl did not print the value), which the caller counts."""
    if isinstance(value, str):
        return [value]
    if not isinstance(value, list):
        return None
    if _byte_list(value):
        return [bytes(value).decode("utf-8", errors="replace")]
    out = []
    for v in value:
        if isinstance(v, str):
            out.append(v)
        elif _byte_list(v):
            out.append(bytes(v).decode("utf-8", errors="replace"))
        else:
            return None
    return out


def _no_repeated_key(pairs):
    d = dict(pairs)
    if len(d) != len(pairs):
        raise ValueError("repeated key")
    return d


def _search_journal(host, argv, secrets, redactor=None, timeout=60, on_message=None):
    """One journalctl call (`argv` ends with JOURNAL_ALL_FIELDS), read entry by entry: every field
    value is parsed out of its JSON and searched for the credential patterns and the known secret
    values; with a redactor, each line of each value is also counted when it looks like
    Google-credential text or (outside CID_SKIP_FIELDS) holds a registered customer id.
    `on_message` gets each MESSAGE text. Counts only (SEARCH_COUNTS), never a value.
    CouldNotCheck, in fixed words: not root on a real host; a non-zero exit; anything on stderr
    (record R14: a damaged file is skipped with a warning and rc 0); an entry that is not a JSON
    object or a field printed as null (what was searched is then unknown)."""
    if _not_root_on_a_real_host(host):
        raise CouldNotCheck("the journal is read as root only")
    c = dict.fromkeys(SEARCH_COUNTS, 0)
    known = [s for s in set(secrets) if len(s) >= 8]
    unparsed = unprinted = 0
    stream = host.stream(argv, timeout)
    it = iter(stream)
    try:
        for line in it:
            c["scanned_characters"] += len(line)
            if not line.strip():
                continue
            try:
                entry = json.loads(line, object_pairs_hook=_no_repeated_key)
            except (ValueError, RecursionError):
                entry = None
            if not isinstance(entry, dict):
                unparsed += 1
                continue
            c["entries"] += 1
            for name, value in entry.items():
                texts = _field_texts(value)
                if texts is None:
                    unprinted += 1
                    continue
                c["fields"] += 1
                for t in texts:
                    c["undecodable_characters"] += t.count("\ufffd")
                    c["pattern_hits"] += len(CRED_TEXT_RE.findall(t))
                    c["known_secret_hits"] += sum(t.count(s) for s in known)
                    if redactor is not None:
                        for l in t.splitlines():
                            c["credential_text_lines"] += 1 if R.looks_like_credential_text(l) else 0
                            if name not in CID_SKIP_FIELDS and redactor.has_customer_id(l):
                                c["customer_id_lines"] += 1
                    if on_message is not None and name == "MESSAGE":
                        on_message(t)
    finally:
        close = getattr(it, "close", None)
        if close is not None:
            close()
    if stream.rc != 0:
        raise CouldNotCheck(f"{argv[0]} exited {stream.rc}")
    if stream.err.strip():
        raise CouldNotCheck(f"{argv[0]} read the journal but wrote a warning on stderr: what it covered is unknown")
    if unparsed or unprinted:
        raise CouldNotCheck(f"{unparsed} journal entries did not parse and {unprinted} fields were not printed: "
                            "what was searched is unknown")
    return c


def d2_3(host, ctx):
    """Every stored field of every entry journalctl shows, as far back as it reaches (D2.4 judges
    how far). The oldest entry is read AFTER the search: entries only ever leave, so the search
    reached at least that far. An oldest entry that cannot be read is could-not-check; the counts
    of the search stay."""
    c = _search_journal(host, ["journalctl", *JOURNAL_ALL_FIELDS], ctx.get("secrets", []),
                        timeout=JOURNAL_SCAN_TIMEOUT)
    return {"journal": {k: c[k] for k in SEARCH_HIT_COUNTS},
            "entries": c["entries"], "fields": c["fields"], "scanned_characters": c["scanned_characters"],
            "undecodable_characters": c["undecodable_characters"], "oldest_entry_read": _oldest_entry_or_unknown(host)}


def _oldest_entry_or_unknown(host, selector=()):
    try:
        return _oldest_entry(host, selector)
    except (OSError, ValueError):                   # the runner itself failed, or its output is not text
        return R.COULD_NOT_CHECK


# D2.4: the journal service's settings. `systemd-analyze cat-config --tldr systemd/journald.conf`
# (systemd 255, measured, record R8/R9) lists the files in the order systemd reads them: a `# <path>`
# header per file, one empty line between files, no comment lines of the contents. It prints lines
# systemd rejects as they are, and a file name holding newlines prints as several lines, so the
# printout decides WHICH files and in what order; the files themselves are read too.
JOURNALD_CAT_CONFIG = ["systemd-analyze", "cat-config", "--tldr", "systemd/journald.conf"]
# Storage= is read too (record R10): with `volatile` or `none` nothing new reaches the disk, while
# the files already there, and our retention, still look healthy.
JOURNALD_SETTINGS = ("MaxRetentionSec", "SystemMaxUse", "SystemMaxFiles", "MaxFileSec", "Storage")
_JOURNALD_MAIN = "/etc/systemd/journald.conf"      # journald 255 reads the main file only here
_JOURNALD_FILE_RE = re.compile(r"/etc/systemd/journald\.conf|"
                               r"/(?:etc|run|usr/lib|usr/local/lib)/systemd/journald\.conf\.d/[A-Za-z0-9._@-]+\.conf")
_JOURNALD_FILE_LIMIT = 64 * 1024
# The directories journald 255 reads drop-ins from (journald.conf(5)), and the only names of a
# settings file in them that this reader accepts.
JOURNALD_DROP_IN_DIRS = ("/etc/systemd/journald.conf.d", "/run/systemd/journald.conf.d",
                         "/usr/local/lib/systemd/journald.conf.d", "/usr/lib/systemd/journald.conf.d")
_JOURNALD_DROP_IN_NAME_RE = re.compile(r"[A-Za-z0-9._@-]+\.conf")
_JOURNALD_ASSIGN_RE = re.compile(r"([A-Za-z][A-Za-z0-9]*)=([\x21-\x5b\x5d-\x7e]*)")
# systemd.time(7) units of one second or more, as integers (src/basic/time-util.c, v255).
_SPAN_UNITS = {"": 1, "seconds": 1, "second": 1, "sec": 1, "s": 1, "minutes": 60, "minute": 60, "min": 60, "m": 60,
               "hours": 3600, "hour": 3600, "hr": 3600, "h": 3600, "days": 86400, "day": 86400, "d": 86400,
               "weeks": 604800, "week": 604800, "w": 604800, "months": 2629800, "month": 2629800, "M": 2629800,
               "years": 31557600, "year": 31557600, "y": 31557600}
_SPAN_RE = re.compile(r"([0-9]{1,9})([A-Za-z]*)")
_SIZE_RE = re.compile(r"([0-9]{1,12})([KMGTPE]?)")
_SIZE_UNITS = {"": 1, "K": 1 << 10, "M": 1 << 20, "G": 1 << 30, "T": 1 << 40, "P": 1 << 50, "E": 1 << 60}
# The oldest entry journalctl would show: its time and nothing else (no message, no host name).
# The selector (a unit, a window) goes AFTER these, so the call never starts as a leak check's does.
OLDEST_ENTRY_ARGS = ["-q", "--no-pager", "-o", "json", "--output-fields=__REALTIME_TIMESTAMP", "-n", "+1"]
# The newest entry of ONE journal directory, after `-D <directory>` (measured, record R13: one
# object and rc 0; nothing and rc 0 for a directory without an entry; rc 1 for a missing one).
NEWEST_ENTRY_ARGS = ["-q", "--no-pager", "-o", "json", "--output-fields=__REALTIME_TIMESTAMP", "-n", "1"]
_TIMESTAMP_RE = re.compile(r"[0-9]{1,17}")


def _span_seconds(value):
    """A systemd time span as whole seconds, or could-not-check. Closed grammar: up to nine digits
    and one unit of a second or more, nothing else (no fraction, blank, sign, several parts), and
    the span must fit systemd's microsecond arithmetic (its parse_time fails when
    digits >= (2**64 - 1) // (unit seconds * 10**6)), so a number returned is one systemd accepts
    and computes the same; anything else is never guessed at."""
    m = _SPAN_RE.fullmatch(value)
    if not m or m.group(2) not in _SPAN_UNITS:
        return R.COULD_NOT_CHECK
    unit = _SPAN_UNITS[m.group(2)]
    if int(m.group(1)) >= (2 ** 64 - 1) // (unit * 10 ** 6):
        return R.COULD_NOT_CHECK
    return int(m.group(1)) * unit


def _size_bytes(value):
    """A size as journald.conf writes it (up to twelve digits and K, M, G, T, P or E, powers of
    1024), below 2**63; otherwise could-not-check."""
    m = _SIZE_RE.fullmatch(value)
    if not m:
        return R.COULD_NOT_CHECK
    n = int(m.group(1)) * _SIZE_UNITS[m.group(2)]
    return n if n < 1 << 63 else R.COULD_NOT_CHECK


def _journald_printout_settings(text):
    """(settings, files) from the `--tldr` printout, by a CLOSED grammar over it: an empty line, a
    `# <path>` header of a journald settings file (each once), exactly `[Journal]`, and `Key=value`
    lines (a key of letters and digits, a value of printable non-blank ASCII without a backslash)
    after the section line of their file. Any other line raises CouldNotCheck; the reason names
    the kind of line, never its content."""
    files, current, section = [], None, False
    last = {k: {"value": None, "file": None} for k in JOURNALD_SETTINGS}
    for line in text.split("\n"):
        if line == "":
            continue
        if line[0] in "#;":
            path = line[2:] if line.startswith("# ") else None
            if path is None or not _JOURNALD_FILE_RE.fullmatch(path):
                raise CouldNotCheck("cat-config shows a comment or a header this reader does not know")
            if path in files:
                raise CouldNotCheck("cat-config shows one settings file twice")
            current, section = path, False
            files.append(path)
        elif current is None:
            raise CouldNotCheck("cat-config shows a line before the first file header")
        elif line[0] == "[":
            if line != "[Journal]":
                raise CouldNotCheck("cat-config shows a section other than [Journal]")
            section = True
        else:
            m = _JOURNALD_ASSIGN_RE.fullmatch(line)
            if not m or not section:
                raise CouldNotCheck("cat-config shows a line this reader does not model")
            if m.group(1) in last:
                last[m.group(1)] = {"value": m.group(2), "file": current}
    if not files:
        raise CouldNotCheck("cat-config shows no settings file")
    if files[0] != _JOURNALD_MAIN and _JOURNALD_MAIN in files:
        raise CouldNotCheck("cat-config shows the main settings file after a drop-in")
    return last, files


def _journald_file_settings(host, files):
    """The same four settings read from the files themselves, in order, by the closed grammar
    systemd's own parser makes safe to model: blank lines and lines whose first non-blank
    character is # or ; are skipped, exactly `[Journal]` is the section, any other line starting
    (after blanks) with `[` raises (systemd stops reading there: record R9), `Key=value` after
    `[Journal]` is read as in the printout, anything else raises. A line ending in a backslash
    or holding a carriage return raises (a continuation or a line end this reader does not model).
    Each listed path must be a regular file (not a link, not a directory, not missing: a missing
    file is a forged header), at most 64 kB, ASCII, without a NUL byte. The path is opened once,
    without following a link in its last part and without waiting on a FIFO, and "regular file"
    is decided on the open file, so what is judged is what is read."""
    last = {k: {"value": None, "file": None} for k in JOURNALD_SETTINGS}
    for path in files:
        try:
            fd = os.open(host.path(path), os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        except OSError:
            raise CouldNotCheck("a settings file cat-config lists cannot be opened, or is a link")
        try:
            if not stat.S_ISREG(os.fstat(fd).st_mode):
                raise CouldNotCheck("a settings file cat-config lists is not a regular file")
            with os.fdopen(os.dup(fd), "rb") as f:
                raw = f.read(_JOURNALD_FILE_LIMIT + 1)
        except OSError:
            raise CouldNotCheck("a settings file cat-config lists cannot be read")
        finally:
            os.close(fd)
        if len(raw) > _JOURNALD_FILE_LIMIT or b"\0" in raw:
            raise CouldNotCheck("a settings file is too large or holds a NUL byte")
        try:
            body = raw.decode("ascii")
        except UnicodeDecodeError:
            raise CouldNotCheck("a settings file holds a byte outside ASCII")
        section = False
        for line in body.split("\n"):
            if "\r" in line or line.endswith("\\"):
                raise CouldNotCheck("a settings file holds a carriage return or a continuation line")
            stripped = line.strip(" \t")
            if not stripped or stripped[0] in "#;":
                continue
            if stripped[0] == "[":
                if line != "[Journal]":
                    raise CouldNotCheck("a settings file holds a section other than [Journal], or a broken one")
                section = True
                continue
            m = _JOURNALD_ASSIGN_RE.fullmatch(line)
            if not m or not section:
                raise CouldNotCheck("a settings file holds a line this reader does not model")
            if m.group(1) in last:
                last[m.group(1)] = {"value": m.group(2), "file": path}
    return last


def _journald_refuse_linked_dirs(host):
    """Raises CouldNotCheck unless every drop-in directory that exists is a real directory reached
    through real directories only (each part of its path, by lstat; the main file's directory is
    among them). Through a link the collector would read files, and compare times, that are not
    those of the place it names: a link's own time does not change when a file is added to or
    removed from the directory behind it. A part that does not exist ends the walk (nothing is
    there); a part that cannot be looked at, or is not a directory, raises."""
    for d in JOURNALD_DROP_IN_DIRS:
        path = ""
        for part in d.strip("/").split("/"):
            path += "/" + part
            try:
                st = os.lstat(host.path(path))
            except FileNotFoundError:
                break
            except OSError:
                raise CouldNotCheck("a journald settings directory cannot be looked at")
            if not stat.S_ISDIR(st.st_mode):
                raise CouldNotCheck("a journald settings directory is a link, or not a directory")


def _journald_refuse_odd_names(host):
    """Raises CouldNotCheck when a drop-in directory holds a `.conf` entry whose name is not a
    plain one, or cannot be listed, or is not a real directory (see above). systemd lists such a
    file, and a name holding newlines makes the printout show header and content lines that stand
    in no file (record R9). A directory that does not exist is fine; a name that does not end in
    `.conf` is not a settings file."""
    _journald_refuse_linked_dirs(host)
    for d in JOURNALD_DROP_IN_DIRS:
        try:
            names = os.listdir(host.path(d))
        except FileNotFoundError:
            continue
        except OSError:
            raise CouldNotCheck("a journald drop-in directory cannot be listed")
        if any(n.endswith(".conf") and not _JOURNALD_DROP_IN_NAME_RE.fullmatch(n) for n in names):
            raise CouldNotCheck("a journald drop-in directory holds an oddly named settings file")


def _journald_settings(host, text):
    """(settings, files): for each name in JOURNALD_SETTINGS the value written LAST under
    [Journal] and the file it stands in (both None when no file sets it), and the files listed,
    in order. Both the `--tldr` printout `text` and the listed files are read, and they must
    agree: the printout decides WHICH files systemd lists and in what order, but it prints lines
    systemd rejects as they are (a broken section line in an earlier file makes systemd stop
    reading, so a later value never applies) and a file name holding newlines forges a header;
    only the files show every line systemd parses. Any line either reading does not model, a
    listed file that is not a regular file on disk, an oddly named settings file in a drop-in
    directory, or a disagreement raises CouldNotCheck."""
    _journald_refuse_odd_names(host)
    printed, files = _journald_printout_settings(text)
    read = _journald_file_settings(host, files)
    if printed != read:
        raise CouldNotCheck("the settings printed by cat-config and the settings read from the files differ")
    return read, files


def _oldest_entry(host, selector=()):
    """The UTC time of the oldest entry journalctl shows for `selector`: None when it shows no
    entry, could-not-check when the answer is not exactly one entry whose time is a string of one
    to seventeen digits above zero."""
    return _entry_time(host, ["journalctl", *OLDEST_ENTRY_ARGS, *selector])


def _entry_time(host, argv):
    """The UTC time of the one entry `argv` (a journalctl call for a single entry, its time only)
    prints: None for no entry, could-not-check for anything but exactly one entry with a time."""
    if _not_root_on_a_real_host(host):
        return R.COULD_NOT_CHECK
    rc, out, err = host.run(argv)
    if rc != 0 or err.strip():              # a warning at rc 0 (a skipped, damaged file): part of the journal was not read
        return R.COULD_NOT_CHECK
    lines = [l for l in out.split("\n") if l.strip()]
    if not lines:
        return None
    try:
        if len(lines) != 1:
            raise ValueError("more than one entry")
        stamp = json.loads(lines[0])["__REALTIME_TIMESTAMP"]
        if not isinstance(stamp, str) or not _TIMESTAMP_RE.fullmatch(stamp) or int(stamp) <= 0:
            raise ValueError("not a timestamp")
        return _iso(int(stamp) // 1000000)
    except (ValueError, KeyError, TypeError, OverflowError, OSError):
        return R.COULD_NOT_CHECK


JOURNAL_DIR = "/var/log/journal"
# systemd's own sign that the journal is on disk (measured, record R13): there once the journal
# was moved to /var, gone after `journalctl --relinquish-var` and still gone after a restart of
# the service, back after `journalctl --flush`.
JOURNAL_FLUSHED_FLAG = "/run/systemd/journal/flushed"
JOURNALD_DROP_IN_DIR = JOURNALD_DROP_IN_DIRS[0]
JOURNALD_DROP_IN = JOURNALD_DROP_IN_DIR + "/50-hermes-retention.conf"
JOURNALD_DROP_IN_REPO = CHECKOUT + "/infra/hermes-agent/deploy/journald-hermes-retention.conf"
JOURNALD_DEFAULT_MAX_FILES = 100                # journald.conf(5), systemd 255: SystemMaxFiles= defaults to 100
JOURNAL_UNITS = {"broker": "hermes-app-broker@" + APP, "runner": "hermes-app-runner@" + APP}
# When the journal service's process now running was started, in UTC to the microsecond (measured,
# systemd 255, record R7). The process reads its settings after this moment, never before it.
# Second precision is not enough: BRING-UP installs our file and restarts the service at once,
# and in the rehearsal the two were 21 ms apart, inside one second.
# With it, whether the service runs at all (record R11): a stopped service keeps this time, shows
# `ActiveState=inactive` and `MainPID=0`. systemd prints the three as `Name=value` lines in its
# own order, so they are read by name.
JOURNALD_STARTED = ["systemctl", "show", "systemd-journald", "--timestamp=us+utc", "-p", "ExecMainStartTimestamp",
                    "-p", "ActiveState", "-p", "MainPID"]
_UNIT_STATE_RE = re.compile(r"[a-z]+(?:-[a-z]+)*")
_PID_RE = re.compile(r"[1-9][0-9]{0,9}")
_SYSTEMD_US_TS_RE = re.compile(r"[A-Z][a-z]{2} ([0-9]{4}-[0-9]{2}-[0-9]{2}) ([0-9]{2}:[0-9]{2}:[0-9]{2})\.([0-9]{6}) UTC")
# A file's times come from the kernel's coarse clock, which can be one tick behind the clock
# systemd reads: 10 ms is the longest tick Linux is built with (HZ=100). A change stamped less
# than this before the start may really have happened after it.
_CLOCK_TICK_NS = 10 * 10 ** 6
# An entry's time and the collector's clock are the same clock, both cut to the second, and the
# entry is read before the clock: an entry later than the clock means the clock went back. Up to
# two seconds is ordinary time-keeping (a small correction between the write and the read) and
# counts as an age of 0; beyond that there is nothing to measure an age with.
_CLOCK_STEP_MARGIN = 2
# SystemMaxFiles as a plain decimal count. A leading zero is refused: systemd's integer parser
# may read it as octal (not measured), and a number is never guessed at.
_MAX_FILES_RE = re.compile(r"0|[1-9][0-9]{0,8}")
_SETTING_NUMBER = {"MaxRetentionSec": _span_seconds, "MaxFileSec": _span_seconds, "SystemMaxUse": _size_bytes,
                   "SystemMaxFiles": lambda v: int(v) if _MAX_FILES_RE.fullmatch(v) else R.COULD_NOT_CHECK,
                   "Storage": lambda v: None}   # a word, not a quantity: the checklist judges `value`


def _percent(part, whole):
    ok = all(isinstance(x, int) and not isinstance(x, bool) for x in (part, whole)) and whole > 0
    return round(100 * part / whole, 1) if ok else R.COULD_NOT_CHECK


def _changed_at_ns(host, p):
    """When a settings file or directory last changed, in nanoseconds: the later of its content
    time and its inode time (a copy that keeps the old content time still shows here). Of the
    path itself, never of a link's target."""
    st = os.lstat(host.path(p))
    return max(st.st_mtime_ns, st.st_ctime_ns)


def _journald_started(host):
    """(active, started_at, start_ns) from JOURNALD_STARTED. `active` is True only when the unit's
    state is `active` AND it has a main process; False when a state is read and is another one;
    could-not-check when the answer is not exactly the three properties, or says `active` without
    a process. The start (UTC to the second, and nanoseconds since the epoch) is given only for a
    running service and only as one UTC time with microseconds: otherwise both are
    could-not-check and None. A time this collector cannot place is never compared, and the start
    of a process that is gone says nothing about what is in force."""
    unknown = (R.COULD_NOT_CHECK, R.COULD_NOT_CHECK, None)
    rc, out, _ = host.run(JOURNALD_STARTED)
    lines = out.split("\n")
    if rc != 0 or lines[-1] != "" or len(lines) != 4:
        return unknown
    got = dict(line.partition("=")[::2] for line in lines[:3] if "=" in line)
    if sorted(got) != ["ActiveState", "ExecMainStartTimestamp", "MainPID"]:
        return unknown
    if not _UNIT_STATE_RE.fullmatch(got["ActiveState"]):
        return unknown
    if got["ActiveState"] != "active":
        return False, R.COULD_NOT_CHECK, None
    if not _PID_RE.fullmatch(got["MainPID"]):
        return unknown
    m = _SYSTEMD_US_TS_RE.fullmatch(got["ExecMainStartTimestamp"])
    if not m:
        return True, R.COULD_NOT_CHECK, None
    iso = f"{m.group(1)}T{m.group(2)}Z"
    try:
        return True, iso, _epoch(iso) * 10 ** 9 + int(m.group(3)) * 1000
    except ValueError:                              # digits that are not a date
        return True, R.COULD_NOT_CHECK, None


def _journald_service(host, files):
    """Whether the journal service runs, when its process started, and whether the settings
    changed after that: the service reads its settings when it starts, so a newer file is not yet
    in force. What is compared: every listed file, and every drop-in directory that exists (its
    time changes when a file in it is added, removed or renamed: a drop-in the service read and
    that was deleted since is still in force and is in no list). Nothing is compared without the
    list of files; nothing is compared and no start is shown for a service that is not running,
    or when a settings directory is not a real directory (its time would be a link's)."""
    row = {"active": R.COULD_NOT_CHECK, "started_at": R.COULD_NOT_CHECK, "config_changed_after_start": R.COULD_NOT_CHECK}
    try:
        row["active"], started, start_ns = _journald_started(host)
        if start_ns is None:
            return row
        _journald_refuse_linked_dirs(host)
        row["started_at"] = started
        if isinstance(files, list) and files:
            times = [_changed_at_ns(host, p) for p in files]
            for d in JOURNALD_DROP_IN_DIRS:
                try:
                    times.append(_changed_at_ns(host, d))
                except FileNotFoundError:
                    pass
            row["config_changed_after_start"] = any(t + _CLOCK_TICK_NS > start_ns for t in times)
    except (CouldNotCheck, OSError, ValueError):
        pass
    return row


def _journal_usage(host, settings):
    """As the service counts it (journal-vacuum.c): the files of the machine's OWN directory,
    512 bytes times each file's blocks. Other directories under /var/log/journal are counted,
    not measured: the service does not trim them and journalctl does not read them. The two
    percentages need the settings: without them, or without a number for the limit, they are
    could-not-check (the size limit has no default this collector assumes).
    Files on disk do not show that the service is writing them (record R13: after
    `journalctl --relinquish-var` an active service with a healthy Storage= writes to /run only,
    and journalctl merges both; a /var it could not open is covered by the age rule and was not
    measured). So the newest entry of the on-disk
    directory ALONE is read, and its age: the machine id goes into that command, never into the
    result. The age cannot show a journal that left the disk a moment ago (150 s in R13), so
    systemd's flag is read too: True when an ordinary file is there, False when
    nothing is, could-not-check for anything else there (a link, a directory) or when it cannot be
    looked at. The machine's directory and /var/log/journal, /var/log, /var must be real
    directories (not links): otherwise all of usage is could-not-check."""
    keys = ("bytes", "files", "bytes_percent_of_max_use", "files_percent_of_max_files", "free_bytes",
            "free_percent", "other_directories", "newest_entry_on_disk", "on_disk_age_seconds", "flushed_to_disk")
    try:
        with open(host.path("/etc/machine-id")) as f:
            mid = f.read(64).strip()
        if not re.fullmatch(r"[0-9a-f]{32}", mid):
            raise ValueError("machine-id")
        base = host.path(JOURNAL_DIR)
        own = os.path.join(base, mid)
        # listdir, statvfs and `journalctl -D` all follow a link: a journal directory linked to a
        # memory file system would read fully healthy. Each part of the path must be a real directory.
        for part in (own, base, os.path.dirname(base), os.path.dirname(os.path.dirname(base))):
            if not stat.S_ISDIR(os.lstat(part).st_mode):
                raise ValueError("journal directory path")
        names = [n for n in os.listdir(own) if n.endswith((".journal", ".journal~"))]
        used = sum(os.lstat(os.path.join(own, n)).st_blocks * 512 for n in names)
        others = sum(1 for n in os.listdir(base) if n != mid and os.path.isdir(os.path.join(base, n)))
        vfs = os.statvfs(own)
    except (OSError, ValueError):
        return {k: R.COULD_NOT_CHECK for k in keys}
    try:
        newest = _entry_time(host, ["journalctl", "-D", JOURNAL_DIR + "/" + mid, *NEWEST_ENTRY_ARGS])
    except (OSError, ValueError):                   # the runner itself failed, or its output is not text
        newest = R.COULD_NOT_CHECK
    age = R.COULD_NOT_CHECK
    if newest is not None and newest != R.COULD_NOT_CHECK:
        seconds = int(time.time()) - _epoch(newest)
        if seconds >= -_CLOCK_STEP_MARGIN:
            age = max(0, seconds)
    try:
        # systemd tests the path with access(), which follows links, so a dangling link is absent
        # for it: only an ordinary file is True; a link, a directory or anything else cannot be judged.
        flushed = True if stat.S_ISREG(os.lstat(host.path(JOURNAL_FLUSHED_FLAG)).st_mode) else R.COULD_NOT_CHECK
    except FileNotFoundError:
        flushed = False
    except OSError:
        flushed = R.COULD_NOT_CHECK
    max_use = max_files = R.COULD_NOT_CHECK
    if isinstance(settings, dict):
        max_use = settings["SystemMaxUse"]["number"]
        max_files = (JOURNALD_DEFAULT_MAX_FILES if settings["SystemMaxFiles"]["value"] is None
                     else settings["SystemMaxFiles"]["number"])
    return {"bytes": used, "files": len(names), "bytes_percent_of_max_use": _percent(used, max_use),
            "files_percent_of_max_files": _percent(len(names), max_files),
            "free_bytes": vfs.f_bavail * vfs.f_frsize, "free_percent": _percent(vfs.f_bavail, vfs.f_blocks),
            "other_directories": others, "newest_entry_on_disk": newest, "on_disk_age_seconds": age,
            "flushed_to_disk": flushed}


def other_journals(host, ctx, secrets):
    """The one-time search of what D2.3 never reads: every real directory under /var/log/journal
    other than the machine's own whose name is a machine id (32 lowercase hex characters); a server
    image can leave the journal of the machine it was built on. Each is read with `journalctl -D`
    and every stored field is searched. Counts only: the directories' names are machine ids and go
    into the command, never into the result. Anything else under the folder (a link, a file,
    `remote`, `<id>.<namespace>`) is not searched and is counted in `skipped_entries`.
    `journalctl -D` reads only `*.journal` and `*.journal~` files directly in a directory and with
    -q may return nothing for a directory where it opened no file, so a directory that holds anything
    else, or files but no entry read, is could-not-check: a clean count would prove nothing.
    Raises CouldNotCheck when a read is not whole, ValueError/OSError when the layout cannot be read."""
    with open(host.path("/etc/machine-id")) as f:
        mid = f.read(64).strip()
    if not re.fullmatch(r"[0-9a-f]{32}", mid):
        raise ValueError("machine-id")
    base = host.path(JOURNAL_DIR)
    for part in (base, os.path.dirname(base), os.path.dirname(os.path.dirname(base))):
        if not stat.S_ISDIR(os.lstat(part).st_mode):
            raise ValueError("journal directory path")
    names, skipped = [], 0
    for n in sorted(os.listdir(base)):
        if n == mid:
            continue
        if re.fullmatch(r"[0-9a-f]{32}", n) and stat.S_ISDIR(os.lstat(os.path.join(base, n)).st_mode):
            names.append(n)
        else:
            skipped += 1
    known = sorted({s for s in secrets if len(s) >= 8})
    total, files, size = dict.fromkeys(SEARCH_COUNTS, 0), 0, 0
    for n in names:
        here = 0
        for name in os.listdir(os.path.join(base, n)):
            st = os.lstat(os.path.join(base, n, name))
            if not stat.S_ISREG(st.st_mode) or not name.endswith((".journal", ".journal~")):
                raise CouldNotCheck("a file journalctl does not read")
            here += 1
            size += st.st_size
        files += here
        c = _search_journal(host, ["journalctl", "-D", JOURNAL_DIR + "/" + n, *JOURNAL_ALL_FIELDS],
                            known, ctx["redactor"], timeout=JOURNAL_SCAN_TIMEOUT)
        if here and c["entries"] == 0:
            raise CouldNotCheck("no entry was read from a directory that holds files")
        for k in total:
            total[k] += c[k]
    return {"directories": len(names), "skipped_entries": skipped, "files": files, "bytes": size,
            "search": total, "known_secrets_checked": len(known)}


def _journald_drop_in(host):
    try:
        st = _stat(host, JOURNALD_DROP_IN)
        row = {"owner": st["owner"], "group": st["group"], "mode": st["mode"]}
    except OSError:
        row = {"owner": R.COULD_NOT_CHECK, "group": R.COULD_NOT_CHECK, "mode": R.COULD_NOT_CHECK}
    try:
        others = sorted(n for n in os.listdir(host.path(JOURNALD_DROP_IN_DIR))
                        if n != os.path.basename(JOURNALD_DROP_IN))
        others = [n if re.fullmatch(r"[A-Za-z0-9._@-]+", n) else WITHHELD for n in others]
    except FileNotFoundError:
        others = []
    except OSError:
        others = R.COULD_NOT_CHECK
    return {"equals_repo": _same_file(host, JOURNALD_DROP_IN, JOURNALD_DROP_IN_REPO), **row, "other_files": others}


def d2_4(host, ctx):
    """How far back the journal reaches and what decides it (F58: the box kept 7 days while the
    leak checks assumed 30). Times, numbers, setting names and settings-file paths only: no
    journal line, no machine id. Each part that cannot be read is could-not-check on its own."""
    def oldest_entry(selector=()):
        try:
            return _oldest_entry(host, selector)
        except (OSError, ValueError):               # the runner itself failed, or its output is not text
            return R.COULD_NOT_CHECK

    oldest = {"journal": oldest_entry()}
    for label, unit in JOURNAL_UNITS.items():
        oldest[label] = oldest_entry(("-u", unit))
    reach = R.COULD_NOT_CHECK
    if oldest["journal"] is None:
        reach = None
    elif oldest["journal"] != R.COULD_NOT_CHECK:
        age = int(time.time()) - _epoch(oldest["journal"])
        if age >= 0:                                # an entry later than this clock: nothing to measure with
            reach = age // 86400
    settings = files = R.COULD_NOT_CHECK
    try:
        got, listed = _journald_settings(host, _ok(host, JOURNALD_CAT_CONFIG))
        settings = {k: {**v, "number": None if v["value"] is None else _SETTING_NUMBER[k](v["value"])}
                    for k, v in got.items()}
        files = listed
    except (CouldNotCheck, OSError, UnicodeDecodeError):
        settings = files = R.COULD_NOT_CHECK
    return {"oldest_entry": oldest, "reach_days": reach, "settings": settings, "config_files": files,
            "drop_in": _journald_drop_in(host), "service": _journald_service(host, files),
            "usage": _journal_usage(host, settings)}


# ---------------------------------------------------------------- D4 isolation boundaries
def _listeners(host, gw):
    """(listeners, docker_dns_listeners) for D4.1. `listeners`: the sorted, distinct local ports
    (decimal) of every socket in state 0A (LISTEN) in the gateway container's /proc/net/tcp and
    /proc/net/tcp6, read in one `docker exec cat`, except those bound to Docker's embedded DNS
    address, which are only counted: `docker_dns_listeners` (gateway_listeners.parse, shared with
    the periodic check). Only ports and the count are kept: no address or other field. Both are
    R.COULD_NOT_CHECK when the call fails, when the output is not exactly two tables (two
    headers), or when any row does not parse."""
    failed = (R.COULD_NOT_CHECK, R.COULD_NOT_CHECK)
    try:
        rc, out, _ = host.run(["docker", "exec", gw, "cat", *GL.PROC_TABLES])
    except (OSError, ValueError):
        return failed
    if rc != 0:
        return failed
    try:
        return GL.parse(out)
    except ValueError:
        return failed


def d4_1(host, ctx):
    gw = _ok(host, ["docker", "ps", "-q", "--no-trunc", "--filter", GATEWAY_FILTER]).strip()
    if len(gw) != 64:
        raise CouldNotCheck(NO_GATEWAY)
    script = ('for p in "$@"; do if [ -e "$p" ]; then if [ -r "$p" ]; then '
              'echo "$p readable $(wc -c < "$p" 2>/dev/null || echo dir)"; else echo "$p unreadable"; fi; '
              'else echo "$p absent"; fi; done')
    out = _ok(host, ["docker", "exec", gw, "sh", "-c", script, "sh", *GATEWAY_PROBE_PATHS, GATEWAY_CONTROL_PATH])
    env = _ok(host, ["docker", "exec", gw, "env"])
    names = [l.split("=", 1)[0] for l in env.splitlines() if "=" in l]
    # Asked before the items ran (collect_with_secrets); asked here when D4.1 runs on its own.
    states = _gateway_secret_states(host, ctx)
    if states == R.COULD_NOT_CHECK:                         # no gateway then: a state for each label all the same
        states = {label: R.COULD_NOT_CHECK for _, label in OTHER_SECRET_NAMES[GATEWAY_ENV_FILE]}
    listeners, dns = _listeners(host, gw)
    return {"paths": out.splitlines(), "secret_env": states,
            "listeners": listeners, "docker_dns_listeners": dns,
            "google_ads_env_names": sorted(n for n in names if n.startswith("GOOGLE_ADS_")),
            "anthropic_env_names": sorted(n for n in names if n.startswith("ANTHROPIC_")),
            "openrouter_env_names": sorted(n for n in names if n.startswith("OPENROUTER_"))}


LAST_PASS_EXECSTART = None      # the last passing review's proxy execstart_sha256, set by main()


def _drop_ins(host, unit):
    """The unit's drop-in files, from a `systemctl show` call of its own: a drop-in changes what
    the unit runs (ExecStart, User, Environment) with the unit file byte-identical. A list of
    paths, empty when there is none; could-not-check when systemd did not print the property."""
    for line in _ok(host, ["systemctl", "show", unit, "-p", "DropInPaths"]).splitlines():
        if line.startswith("DropInPaths="):
            return line[len("DropInPaths="):].split()
    return R.COULD_NOT_CHECK


def _argv_sha256(execstart):
    """sha256 of the `argv[]=...` segment of the ExecStart line(s), or None when there is none.
    Unlike the whole line, it does not carry `start_time` or `pid`, so a restart leaves it
    unchanged. The segment runs up to ` ; ignore_errors=`, the field systemd prints next (the
    last one on the line, so an argument that itself holds ` ; ` cannot end it early); only
    when that field is absent, up to the next ` ; `."""
    segments = []
    for line in execstart.splitlines():
        m = _ARGV_RES[0].search(line)
        if m:
            segments.append(m.group(0)[:-len(" ; ignore_errors=")])
            continue
        m = _ARGV_RES[1].search(line)
        if m:
            segments.append(m.group(0)[:-len(" ; ")])
    return PK.sha256_bytes("\n".join(segments).encode()) if segments else None


def d4_2(host, ctx):
    active = host.run(["systemctl", "is-active", "hermes-docker-proxy"])[1].strip()
    execstart = _ok(host, ["systemctl", "show", "hermes-docker-proxy", "-p", "ExecStart"])
    sha = PK.sha256_bytes(execstart.encode())
    return {"active": active, "execstart_sha256": sha, "last_pass_execstart_sha256": LAST_PASS_EXECSTART,
            "matches_last_pass": None if LAST_PASS_EXECSTART is None else sha == LAST_PASS_EXECSTART,
            # The baseline for the NEXT review, not compared in this one.
            "execstart_argv_sha256": _argv_sha256(execstart),
            "drop_in_paths": _drop_ins(host, "hermes-docker-proxy")}


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


LISTENER_UNITS = ("hermes-listener-check.service", "hermes-listener-check.timer")
LISTENER_TIMER = "hermes-listener-check.timer"
_LISTENER_CHECK = None


def _listener_check():
    """check-gateway-listeners.py as a module (its name has hyphens), loaded once: D4.5 reads the
    check's state with the check's own reader, so the two cannot disagree about a file."""
    global _LISTENER_CHECK
    if _LISTENER_CHECK is None:
        import importlib.util
        spec = importlib.util.spec_from_file_location("check_gateway_listeners",
                                                      os.path.join(HERE, "check-gateway-listeners.py"))
        _LISTENER_CHECK = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(_LISTENER_CHECK)
    return _LISTENER_CHECK


def d4_5(host, ctx):
    """The periodic listener check (F50): is its timer running, are its units the reviewed ones,
    and what has it recorded since the last review. `last` is the latest result (null when the
    check never ran), `alert_present` and `alert` the marker the first alert leaves until the
    operator clears it, `history_counts` every recorded run by status (about a month of them),
    `alert_log` the counts and the first and last time of every alert and clearing ever recorded
    (never trimmed). The check reads the gateway's sockets from the HOST's /proc, D4.1 from inside
    the container: the checklist compares the two. Ports, counts, fixed words and timestamps only. is-active and is-enabled exit non-zero for every state but the good one:
    the state is the answer; no answer at all is could-not-check."""
    L = _listener_check()
    state = L.summary(host.path(L.STATE_DIR), R.utc_now())
    return {"timer_active": host.run(["systemctl", "is-active", LISTENER_TIMER])[1].strip() or R.COULD_NOT_CHECK,
            "timer_enabled": host.run(["systemctl", "is-enabled", LISTENER_TIMER])[1].strip() or R.COULD_NOT_CHECK,
            "installed_equal_repo": {u: _same_file(host, "/etc/systemd/system/" + u,
                                                   CHECKOUT + "/infra/hermes-agent/deploy/" + u)
                                     for u in LISTENER_UNITS},
            "drop_in_paths": {u: _drop_ins(host, u) for u in LISTENER_UNITS},
            # The alert log's "never trimmed" rests on who may write here: root, 0700, a real directory.
            "state_dir": _dir_row(host, L.STATE_DIR),
            "max_age_seconds": L.MAX_AGE_SECONDS,
            **state}


# D4.6: when each service started, and whether it runs older code than the box holds.
LAST_PASS_COLLECTED_AT = None   # the last passing review's box-bundle collected_at, set by main()
# Each long-running Hermes service: its unit file and the script its ExecStart runs (tested
# against the repo's unit files). The files it loads are read from the script itself.
SERVICE_FILES = {"hermes-docker-proxy": ("hermes-docker-proxy.service", "docker-create-proxy.py"),
                 "hermes-broker": ("hermes-broker.service", "hermes-broker.py"),
                 "hermes-app-broker@" + APP: ("hermes-app-broker@.service", "hermes-app-broker.py")}
# The other starts D4.6 reports. The journal service since v1.20 (review #10, entry 8): its restart
# changes what the journal holds from then on, and an automatic update can cause one.
OTHER_STARTS = ("boot", "docker", "systemd-journald", "gateway-container")
_ISO_FORMAT = "%Y-%m-%dT%H:%M:%SZ"
_ISO_RE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z")
_SYSTEMD_TS_RE = re.compile(r"[A-Z][a-z]{2} ([0-9]{4}-[0-9]{2}-[0-9]{2}) ([0-9]{2}:[0-9]{2}:[0-9]{2}) UTC")
_DOCKER_TS_RE = re.compile(r"([0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2})(\.[0-9]+)?Z")
_PY_NAME_RE = re.compile(r"[A-Za-z0-9_-]+\.py")


def _iso(epoch):
    return datetime.datetime.fromtimestamp(epoch, datetime.timezone.utc).strftime(_ISO_FORMAT)


def _epoch(iso):
    return calendar.timegm(time.strptime(iso, _ISO_FORMAT))


def _unit_started_at(host, unit):
    """The unit's ActiveEnterTimestamp as UTC, second precision. Empty (the unit never became
    active), another time zone, or any other form is could-not-check: a time this collector
    cannot place is never compared."""
    rc, out, _ = host.run(["systemctl", "show", unit, "-p", "ActiveEnterTimestamp", "--value"])
    m = _SYSTEMD_TS_RE.fullmatch(out.strip()) if rc == 0 else None
    return f"{m.group(1)}T{m.group(2)}Z" if m else R.COULD_NOT_CHECK


def _gateway_started_at(host):
    rc, gw, _ = host.run(["docker", "ps", "-q", "--no-trunc", "--filter", GATEWAY_FILTER])
    if rc != 0 or len(gw.strip()) != 64:
        return R.COULD_NOT_CHECK
    rc, out, _ = host.run(["docker", "inspect", "--format", "{{.State.StartedAt}}", gw.strip()])
    m = _DOCKER_TS_RE.fullmatch(out.strip()) if rc == 0 else None
    return m.group(1) + "Z" if m else R.COULD_NOT_CHECK


def _boot_at(host):
    try:
        with open(host.path("/proc/stat")) as f:
            for line in f:
                if line.startswith("btime "):
                    return _iso(int(line.split()[1]))
    except (OSError, ValueError, IndexError):
        pass
    return R.COULD_NOT_CHECK


def _loaded_files(bin_dir, script):
    """The bin/ files `script` loads: itself, every bin module it imports at any depth (an
    import inside a function included), and any bin file it names in a string ending `.py`
    (loaded by path, as the collector loads the listener check). Read from the files as they
    are now, so the list cannot fall behind the code. A module imported only on a rare path is
    listed too: that errs towards a restart, never away from one."""
    seen, todo = set(), [script]
    while todo:
        name = todo.pop()
        if name in seen:
            continue
        seen.add(name)
        with open(os.path.join(bin_dir, name), encoding="utf-8") as f:
            tree = ast.parse(f.read())
        for node in ast.walk(tree):
            names = []
            if isinstance(node, ast.Import):
                names = [a.name.split(".")[0] + ".py" for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                names = [node.module.split(".")[0] + ".py"]
            elif isinstance(node, ast.Constant) and isinstance(node.value, str) and _PY_NAME_RE.fullmatch(node.value):
                names = [node.value]
            todo.extend(n for n in names if os.path.isfile(os.path.join(bin_dir, n)))
    return sorted(seen)


def _files_newer_than_start(host, unit, started_at):
    """(names, count): the loaded files whose modification time is later than the service's
    start, and how many files were looked at. `unit` stands for the unit file. The start has
    second precision, so a file changed in that same second is not listed."""
    if started_at == R.COULD_NOT_CHECK:
        return R.COULD_NOT_CHECK, R.COULD_NOT_CHECK
    unit_file, script = SERVICE_FILES[unit]
    bin_dir = host.path(AGENT_DIR + "/bin")
    try:
        paths = {"unit": host.path("/etc/systemd/system/" + unit_file)}
        paths.update({n: os.path.join(bin_dir, n) for n in _loaded_files(bin_dir, script)})
        start = _epoch(started_at)
        return sorted(n for n, p in paths.items() if int(os.stat(p).st_mtime) > start), len(paths)
    except (OSError, SyntaxError, ValueError, RecursionError):
        return R.COULD_NOT_CHECK, R.COULD_NOT_CHECK


def d4_6(host, ctx):
    """When the host, Docker, the three long-running Hermes services and the gateway container
    last started, each compared with the last PASS's collection time (given with
    --last-pass-collected-at), and which files each service loads that changed after it
    started. D4.2's hash is the same string after any daemon-reload, so it cannot show a
    restart (review #8); this item can. Timestamps, unit names and file names only."""
    starts = {"boot": _boot_at(host), "docker": _unit_started_at(host, "docker"),
              "systemd-journald": _unit_started_at(host, "systemd-journald"),
              **{u: _unit_started_at(host, u) for u in SERVICE_FILES},
              "gateway-container": _gateway_started_at(host)}
    base = LAST_PASS_COLLECTED_AT

    def after(ts):
        if ts == R.COULD_NOT_CHECK:
            return R.COULD_NOT_CHECK
        return None if base is None else ts > base       # one fixed-width UTC format: text order is time order

    files = {u: _files_newer_than_start(host, u, starts[u]) for u in SERVICE_FILES}
    return {"last_pass_collected_at": base, "started_at": starts,
            "started_after_last_pass": {k: after(v) for k, v in starts.items()},
            "files_newer_than_start": {u: f[0] for u, f in files.items()},
            "files_checked": {u: f[1] for u, f in files.items()}}


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
            # The app's `.env` is masked from the executor and must stay EMPTY: it is exempt
            # from `extra` only while it is 0 bytes, so a filled one cannot pass silently
            # (review #3, not-on-checklist #4).
            env = host.path(d + "/.env")
            env_size = os.lstat(env).st_size if os.path.lexists(env) else 0
            allowed = {e["path"] for e in m["files"]} | {PK.MANIFEST_NAME}
            if env_size == 0:
                allowed.add(".env")
            extra = []
            for root, _, names in os.walk(host.path(d)):
                for n in names:
                    rel = os.path.relpath(os.path.join(root, n), host.path(d))
                    if rel not in allowed:
                        extra.append(rel)
            row.update(installed_sha256=PK.sha256_bytes(raw), commit=m["commit"],
                       files=len(m["files"]), mismatched=bad, extra=sorted(extra),
                       env_file={"present": os.path.lexists(env), "size": env_size})
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
def _reg_status(reg, name):
    """active | retired | ... from the registry, never the slug; a name it lacks is unregistered."""
    e = reg.get(name)
    if e is None:
        return "unregistered"
    return e.get("status", "unknown") if isinstance(e, dict) else "unknown"


def _dir_row(host, p):
    """owner, group, mode of a directory (lstat, never followed); 'absent'; or 'symlink' / 'not-a-directory'."""
    try:
        st = os.lstat(host.path(p))
    except FileNotFoundError:
        return "absent"
    if stat.S_ISLNK(st.st_mode):
        return "symlink"
    if not stat.S_ISDIR(st.st_mode):
        return "not-a-directory"
    return {"owner": _owner(st.st_uid), "group": _group(st.st_gid), "mode": oct(stat.S_IMODE(st.st_mode))}


def _file_modes(cdir, st):
    """Counts of the entries inside one client directory by "owner group mode", never names.
    A symlink or non-directory is not listed; an entry that vanishes is skipped and a
    directory that cannot be listed gives no counts, never an exception out of D7.1."""
    files = {}
    if not stat.S_ISDIR(st.st_mode):               # lstat: a symlink is not S_ISDIR
        return files
    try:
        names = os.listdir(cdir)
    except OSError:
        return files
    for fn in names:
        try:
            fst = os.lstat(os.path.join(cdir, fn))
        except OSError:
            continue
        k = f"{_owner(fst.st_uid)} {_group(fst.st_gid)} {oct(stat.S_IMODE(fst.st_mode))}"
        files[k] = files.get(k, 0) + 1
    return files


def _audit_logs(host, reg):
    """The audit-logs root plus one row per child: registry status, owner, mode, never the name.
    A symlinked root is reported as such and never listed."""
    root = "/var/lib/hermes/audit-logs"
    row = _dir_row(host, root)
    rows = []
    if isinstance(row, dict):
        for name in sorted(os.listdir(host.path(root))):
            st = os.lstat(os.path.join(host.path(root), name))
            rows.append({"status": _reg_status(reg, name),
                         "owner": _owner(st.st_uid), "mode": oct(stat.S_IMODE(st.st_mode)),
                         "files": _file_modes(os.path.join(host.path(root), name), st)})
    return {"root": row, "rows": rows}


HERMES_VAR = "/var/lib/hermes"


def _client_rows(host, reg, parent):
    """One row per child of a client-data parent: registry status, owner, mode, never the name.
    A symlinked or non-directory parent is not listed; a child that vanishes is skipped."""
    root = host.path(parent)
    rows = []
    if os.path.isdir(root) and not os.path.islink(root):
        try:
            names = sorted(os.listdir(root))
        except OSError:
            names = []
        for name in names:
            try:
                st = os.lstat(os.path.join(root, name))
            except OSError:
                continue
            rows.append({"status": _reg_status(reg, name), "owner": _owner(st.st_uid),
                         "mode": oct(stat.S_IMODE(st.st_mode))})
    return rows


def d7_1(host, ctx):
    with open(host.path(GOV + "/registry/clients.json")) as f:     # one read for both row kinds
        reg = json.load(f).get("clients", {})
    records = host.path(GOV + "/records")
    backups = sorted(n for n in os.listdir(host.path("/root")) if n.startswith("live-gate-")) \
        if os.path.isdir(host.path("/root")) else []
    audit = []
    ad_root = host.path("/var/lib/hermes/audit-data")
    if os.path.isdir(ad_root):
        for name in sorted(os.listdir(ad_root)):
            st = os.lstat(os.path.join(ad_root, name))
            audit.append({"status": _reg_status(reg, name),
                          "owner": _owner(st.st_uid), "mode": oct(stat.S_IMODE(st.st_mode))})
    return {"vaults": _client_rows(host, reg, HERMES_VAR + "/vaults"),
            "reports_rows": _client_rows(host, reg, HERMES_VAR + "/reports"),
            "draft_out_rows": _client_rows(host, reg, HERMES_VAR + "/draft-out"),
            "parents": {d: _dir_row(host, f"{HERMES_VAR}/{d}") for d in ("vaults", "reports", "draft-out")},
            "old_data": {"data/vaults": _dir_row(host, AGENT_DIR + "/data/vaults"),
                         "data/reports": _dir_row(host, AGENT_DIR + "/data/reports")},
            "audit_data": audit,
            "audit_logs": _audit_logs(host, reg),
            "records": sum(len(fs) for _, _, fs in os.walk(records)) if os.path.isdir(records) else 0,
            "root_backups": [{"dir": b, "files": len(os.listdir(host.path("/root/" + b)))} for b in backups]}


# ---------------------------------------------------------------- D10 chat-triggered audits
def _json_probe(host, flag):
    """run-client-audit's probe: one JSON object on stdout, exit 0 (match) or 1 (mismatch).
    Anything else — exit 3 with nothing while an audit holds the lock, 124 on a timeout, a
    traceback — is could-not-check, with the exit code and never the output."""
    rc, out, _ = host.run(["run-client-audit", flag], timeout=PROBE_TIMEOUT)
    try:
        probe = json.loads(out)
    except (ValueError, RecursionError):
        probe = None
    if not isinstance(probe, dict):
        raise CouldNotCheck(f"run-client-audit {flag} exited {rc} without a JSON object")
    return {"rc": rc, "probe": probe}


def d10_1(host, ctx):
    return _json_probe(host, "--probe-env")


def d10_2(host, ctx):
    return _json_probe(host, "--probe-egress")


def _env_names(value):
    """The variable NAMES in a systemd Environment= value. A value never reaches the bundle: a
    token that is not NAME=value (no `=`, or what precedes it is not a variable name) is `?`."""
    try:
        return sorted({tok.partition("=")[0] if "=" in tok and _ENV_NAME_RE.fullmatch(tok.partition("=")[0])
                       else "?" for tok in shlex.split(value)})
    except ValueError:
        return R.COULD_NOT_CHECK


def _unit_props(host, unit, props):
    """`systemctl show -p` for the properties asked for, and nothing else it printed. systemd
    prints a requested property even when empty, so one it did not print is could-not-check —
    except EnvironmentFiles, which it prints once per file and not at all when there is none."""
    out = _ok(host, ["systemctl", "show", unit, "-p", ",".join(props)])
    got = {p: [] if p == "EnvironmentFiles" else R.COULD_NOT_CHECK for p in props}
    for line in out.splitlines():
        k, sep, v = line.partition("=")
        if not sep or k not in got:
            continue
        if k == "EnvironmentFiles":
            got[k].append(v)
        else:
            got[k] = _env_names(v) if k == "Environment" else v
    return got


def _same_file(host, a, b):
    """True only when both files can be read and are byte-identical."""
    try:
        return PK.sha256_file(host.path(a)) == PK.sha256_file(host.path(b))
    except OSError:
        return False


def _sudo_rules(host, user):
    """`sudo -l -U <user>` as shape only: its text names the host, and its rules are not ours to
    print. It has two answers, "is not allowed to run sudo" and "may run the following commands";
    with neither (sudo did not run, an unknown user, another locale) nothing was learned."""
    rc, out, _ = host.run(["sudo", "-l", "-U", user])
    lines = out.splitlines()
    grant = next((i for i, l in enumerate(lines) if "may run the following commands" in l), None)
    not_allowed = any("is not allowed to run sudo" in l for l in lines)
    if grant is None and not not_allowed:
        return {"rc": rc, "not_allowed": R.COULD_NOT_CHECK, "command_lines": R.COULD_NOT_CHECK}
    return {"rc": rc, "not_allowed": not_allowed,
            "command_lines": 0 if grant is None else sum(1 for l in lines[grant + 1:] if l.strip())}


def d10_3(host, ctx):
    # is-active exits non-zero for every state but `active`: the state is the answer, not a failure.
    path_state = host.run(["systemctl", "is-active", f"hermes-app-runner@{APP}.path"])[1].strip()
    # A missing app user is `id`'s non-zero exit: it costs this value, not the unit properties.
    rc, groups, _ = host.run(["id", "-nG", APP_USER])
    return {"broker_unit": _unit_props(host, f"hermes-app-broker@{APP}", BROKER_PROPS),
            "runner_unit": _unit_props(host, f"hermes-app-runner@{APP}", ENV_PROPS),
            "installed_equal_repo": {u: _same_file(host, "/etc/systemd/system/" + u,
                                                   CHECKOUT + "/infra/hermes-agent/deploy/" + u)
                                     for u in APP_UNITS},
            # The instances of those three templates: equal unit files prove nothing with a drop-in.
            "drop_in_paths": {u: _drop_ins(host, u) for u in (t.replace("@.", f"@{APP}.") for t in APP_UNITS)},
            "broker_user_groups": groups.split() if rc == 0 else R.COULD_NOT_CHECK,
            "sudo_rules": _sudo_rules(host, APP_USER),
            "runner_path_active": path_state or R.COULD_NOT_CHECK}


def _exposes_app_state(source):
    """A mount whose host side is app-state, a path inside it, or a directory above it."""
    s, root = os.path.normpath(source), HL.DEFAULT_STATE_ROOT
    return s == root or s.startswith(root + "/") or root.startswith(s.rstrip("/") + "/")


def d10_4(host, ctx):
    try:
        problems = HL.check_app(APP, host.path(HL.DEFAULT_APPS_ROOT), host.path(HL.DEFAULT_STATE_ROOT),
                                HL.system_resolver(layout=HL.app_layout(APP)), ancestor_top=host.root)
    except HL.LayoutError as e:
        raise CouldNotCheck(f"layout: {e}")
    ids = _ok(host, ["docker", "ps", "-q", "--no-trunc"]).split()
    mounting = not_inspected = 0
    for cid in ids:
        # A container that went away, or Mounts that are not what Docker prints, is counted —
        # never allowed to fail the item or to pass as "mounts nothing".
        rc, out, _ = host.run(["docker", "inspect", "--format", "{{json .Mounts}}", cid])
        try:
            mounts = json.loads(out) if rc == 0 else None
        except (ValueError, RecursionError):
            mounts = None
        if not isinstance(mounts, list) or not all(isinstance(m, dict) and isinstance(m.get("Source"), str)
                                                   for m in mounts):
            not_inspected += 1
        elif any(_exposes_app_state(m["Source"]) for m in mounts):
            mounting += 1
    return {"layout_problems": problems, "containers": len(ids),
            "containers_mounting_app_state": mounting, "containers_not_inspected": not_inspected}


def _config_text(path, what):
    """A config file's text. The read refuses a symlink, anything but a regular file and a file
    over MCP_CONFIG_CAP, and never blocks: a refusal is could-not-check. `what` names the file in
    that reason, never its content. Bytes that are not UTF-8 become U+FFFD, which mcp_config
    refuses."""
    try:
        return A.read_capped(path, MCP_CONFIG_CAP).decode("utf-8", errors="replace")
    except (A.Refused, OSError) as e:
        raise CouldNotCheck(f"{what}: {e if isinstance(e, A.Refused) else type(e).__name__}")


def _no_credential_lines(lines):
    return [WITHHELD if R.looks_like_credential_text(l) else l for l in lines]


def _cut_listing(lines, secrets):
    """Each line cut to MCP_LIST_WIDTH, except one that holds a known secret value: that line is
    kept whole, so the whole-bundle refusal (assert_no_secret in main) still fires on it and no
    part of a secret that straddles the cut is ever printed. A secret never spans lines, so the
    line cap needs no such care."""
    known = [s for s in secrets if len(s) >= 8]
    return [l if any(s in l for s in known) else l[:MCP_LIST_WIDTH] for l in lines]


def d10_6(host, ctx):
    """The box's file is free text from the reviewed party, so none of it is emitted: only
    whether its `mcp_servers:` block holds the committed block's values (mcp_config parses both
    with one strict parser; layout, quoting, comments and mapping key order do not count), a
    reason from mcp_config.REASONS when it does not, and the sha256 of its canonical form when it
    parsed. The template is ours: when IT has no block the parser reads, nothing can be compared."""
    box = _config_text(host.path(MCP_BOX_CONFIG), "data/config.yaml")
    repo = _config_text(host.path(MCP_REPO_CONFIG), "config.yaml.example")
    try:
        block = mcp_config.compare(box, repo)
    except ValueError:
        raise CouldNotCheck("config.yaml.example: no usable mcp_servers block")
    # The tool list is information, not a boundary: when it cannot be had, it is empty with its
    # exit code (None: no gateway container to ask), and the comparison is still reported. It is
    # the gateway's own text: capped in lines and in line length, and emitted only when the values
    # to look for in it are known, which is when every D4.1 secret_env state was measured. Not
    # asked here (collect_with_secrets or D4.1 did): without that, or with one label that could
    # not be checked, the listing is could-not-check and only its exit code is reported.
    states = ctx.get("secret_env")
    measured = isinstance(states, dict) and R.COULD_NOT_CHECK not in states.values()
    rc, gw, _ = host.run(["docker", "ps", "-q", "--no-trunc", "--filter", GATEWAY_FILTER])
    gw, listing, list_rc = gw.strip(), [], None
    if rc == 0 and len(gw) == 64:
        list_rc, out, _ = host.run(["docker", "exec", gw, "hermes", "mcp", "list"])
        if list_rc == 0 and measured:
            listing = _cut_listing(_no_credential_lines(out.splitlines()[:MCP_LIST_LINES]),
                                   ctx.get("secrets", []))
    return {"mcp_block": block, "gateway_mcp_list": listing if measured else R.COULD_NOT_CHECK,
            "gateway_mcp_list_rc": list_rc}


def _label(value, allowed):
    """A closed-set value as itself, null as `-`, anything else as `?`: free text, a name or a
    wrong type from a file or a journal line never reaches the bundle."""
    if value is None:
        return "-"
    return value if isinstance(value, str) and value in allowed else "?"


SEARCH_HIT_COUNTS = ("pattern_hits", "known_secret_hits")
LEAK_COUNTS = ("credential_text_lines", "customer_id_lines", "pattern_hits", "known_secret_hits")
READ_COUNTS = ("entries", "fields", "undecodable_characters")


def _unit_search(host, unit, secrets, redactor, on_message=None):
    """What a unit's journal of the last 30 days must hold none of, in every stored field: lines
    of Google-credential-shaped text, lines with a registered customer id, credential patterns and
    the installed secret values themselves. Counts only, never a line."""
    return _search_journal(host, ["journalctl", "-u", unit, "--since", "-30d", *JOURNAL_ALL_FIELDS],
                           secrets, redactor, on_message=on_message)


def d10_7(host, ctx):
    """Counts only, never a line or a field: the journal names clients and request ids by design. The
    status/reason counts are the broker's; the leak counts cover the runner's journal too,
    which is where run-client-audit's own output lands (its unit sets no StandardOutput)."""
    # The non-Google values are loaded before the probes; D2.1 (it runs first) adds the Google
    # ones and any other it finds. With none
    # loaded, known_secret_hits can only be 0: known_secrets_checked says how many were looked for.
    secrets = sorted({s for s in ctx.get("secrets", []) if len(s) >= 8})
    lines = []
    broker = _unit_search(host, f"hermes-app-broker@{APP}", secrets, ctx["redactor"],
                          on_message=lambda t: lines.extend(t.splitlines()))
    runner = _unit_search(host, f"hermes-app-runner@{APP}", secrets, ctx["redactor"])
    oldest = {label: _oldest_entry_or_unknown(host, ("-u", unit, "--since", "-30d"))
              for label, unit in JOURNAL_UNITS.items()}
    counts, notes, other = {}, {}, 0
    for line in lines:
        if not line.strip():
            continue
        body = line[len(_BROKER_LINE):] if line.startswith(_BROKER_LINE) else ""
        say, note = _SAY_RE.fullmatch(body), _NOTE_RE.match(body)
        if say:
            k = f"{_label(say.group(1), JOURNAL_STATUSES)}/{_label(say.group(2), JOURNAL_REASONS)}"
            counts[k] = counts.get(k, 0) + 1
        elif note:
            notes[note.group(1)] = notes.get(note.group(1), 0) + 1
        else:
            other += 1                                      # systemd's own lines, a traceback, anything else
    return {"journal_counts": counts, "note_counts": notes, "other_lines": other,
            "broker_journal": {k: broker[k] for k in LEAK_COUNTS},
            "runner_journal": {k: runner[k] for k in LEAK_COUNTS},
            "journal_read": {"broker": {k: broker[k] for k in READ_COUNTS},
                             "runner": {k: runner[k] for k in READ_COUNTS}},
            "known_secrets_checked": len(secrets), "oldest_entry_read": oldest}


def d10_8(host, ctx):
    """One row per entry in results/, whatever it is. An entry that cannot be read as a JSON
    object (unreadable, not a regular file, too large, malformed) is a row and is out of
    whitelist, as is a result stored under a name that is not its own request id. Rows carry
    closed-set labels only: never the slug, the request id or a file name."""
    d = host.path(APP_RESULTS)
    rows, bad = [], 0
    for n in sorted(os.listdir(d)):
        # Everything done with one entry sits inside this guard: whatever a file holds, and
        # whatever goes wrong judging it, costs that entry's row and never the other rows.
        try:
            obj = json.loads(A.read_capped(os.path.join(d, n), A.MAX_DONE_BYTES))
            if not isinstance(obj, dict):
                raise ValueError("not an object")
            keys_ok, values_ok = A.result_in_whitelist(obj)
            values_ok = values_ok and obj["request_id"] + ".json" == n
            row = {"op": _label(obj.get("op"), A.KNOWN_OPS),
                   "status": _label(obj.get("status"), A.STATUSES),
                   "reason": _label(obj.get("reason"), A.BROKER_REASONS + A.COMMAND_REASONS),
                   "keys_ok": keys_ok, "values_ok": values_ok}
        except Exception:                                   # OSError, ValueError (A.Refused), RecursionError, ...
            row = {"keys_ok": False, "values_ok": False}
        rows.append(row)
        bad += not (row["keys_ok"] and row["values_ok"])
    return {"results": rows, "out_of_whitelist": bad}


PROBES = {"D1.1": d1_1, "D1.2": d1_2, "D1.3": d1_3, "D1.4": d1_4, "D1.5": d1_5, "D1.6": d1_6, "D1.7": d1_7,
          "D2.1": d2_1, "D2.2": d2_2, "D2.3": d2_3, "D2.4": d2_4,
          "D4.1": d4_1, "D4.2": d4_2, "D4.3": d4_3, "D4.4": d4_4, "D4.5": d4_5, "D4.6": d4_6,
          "D5.1": d5_1, "D5.2": d5_2, "D5.3": d5_3, "D5.4": d5_4,
          "D6.1": d6_1, "D6.2": d6_2, "D7.1": d7_1,
          # D10.5 (the OpenRouter key limit and account privacy setting) is manual: no probe.
          "D10.1": d10_1, "D10.2": d10_2, "D10.3": d10_3, "D10.4": d10_4, "D10.6": d10_6,
          "D10.7": d10_7, "D10.8": d10_8}


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
        # Note: on an iptables-legacy host `nft -s list ruleset` succeeds but returns an
        # empty ruleset (rc 0, no rules) rather than failing, so the iptables-save
        # fallback below never runs there — not the case on this box (Ubuntu 24.04's
        # nft/nftables backend), where nft is authoritative.
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
def _collect(host, fp_key):
    """(bundle, secrets, ctx): the bundle BEFORE redaction, every credential value seen (for
    assert_no_secret) and the run's ctx. Only main and collect_with_secrets call this: nothing
    else may hold the unredacted bundle."""
    ctx = context(host, fp_key)
    items = {}
    # The non-Google secrets are loaded first and on their own, so the leak checks (D2.2, D2.3,
    # D10.7) search for them whether or not the sweep reaches the files. Every value read is
    # seeded, also from a file reported in other_failed.
    other, other_secrets, other_failed = other_credentials(host)
    _seed(ctx, other_secrets)
    # Then the values the running gateway really holds, however the file spells them (F43).
    _gateway_secret_states(host, ctx)
    for iid, fn in PROBES.items():
        try:
            items[iid] = {"status": R.OBSERVED, "data": fn(host, ctx)}
        except (CouldNotCheck, OSError, ValueError, KeyError, IndexError) as e:
            items[iid] = {"status": R.COULD_NOT_CHECK, "reason": f"{type(e).__name__}: {e}"}
    try:
        sweep = _shared_sweep(host, ctx)                   # A3: reuse D2.1's sweep, don't re-run find
        infos, secrets, _unparsed, _unreadable = installed_credentials(host, sweep=sweep)
        creds = ({R.COULD_NOT_CHECK: "; ".join(other_failed)} if other_failed
                 else R.credential_set(infos) + other)
    except CouldNotCheck as e:
        secrets, creds = [], {R.COULD_NOT_CHECK: str(e)}
    bundle = {"schema": 1, "kind": "box", "collected_at": R.utc_now(), "items": items,
              "fingerprint": box_fingerprint(host, ctx), "credentials": creds,
              "cid_fingerprint": "hmac-sha256/12", "cid_key_id": R.key_id(fp_key)}
    return bundle, ctx.get("secrets", []) + secrets, ctx


def collect_with_secrets(host, fp_key):
    """The bundle (redacted) and every credential value seen, for assert_no_secret."""
    bundle, secrets, ctx = _collect(host, fp_key)
    return ctx["redactor"].obj(bundle), secrets


def collect(host, fp_key):
    return collect_with_secrets(host, fp_key)[0]


def _valid_collected_at(value):
    if not _ISO_RE.fullmatch(value):
        return False
    try:
        _epoch(value)
    except ValueError:
        return False
    return True


def main(argv=None, host=None, read_key=_tty_key):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--fingerprint-only", action="store_true")
    g.add_argument("--credentials-only", action="store_true")
    g.add_argument("--other-journals", action="store_true")
    ap.add_argument("--fp-key-tty", action="store_true")
    ap.add_argument("--last-pass-execstart")
    ap.add_argument("--last-pass-collected-at")
    a = ap.parse_args(argv)
    if a.last_pass_execstart is not None and not re.fullmatch(r"[0-9a-f]{64}", a.last_pass_execstart):
        print("collect-review-evidence: --last-pass-execstart must be 64 lowercase hex characters",
              file=sys.stderr)
        return 2
    if a.last_pass_collected_at is not None and not _valid_collected_at(a.last_pass_collected_at):
        print("collect-review-evidence: --last-pass-collected-at must be the last PASS bundle's collected_at, "
              "a UTC time such as 2026-10-07T16:21:22Z", file=sys.stderr)
        return 2
    global LAST_PASS_EXECSTART, LAST_PASS_COLLECTED_AT
    prior = LAST_PASS_EXECSTART, LAST_PASS_COLLECTED_AT
    if a.last_pass_execstart is not None:
        LAST_PASS_EXECSTART = a.last_pass_execstart
    if a.last_pass_collected_at is not None:
        LAST_PASS_COLLECTED_AT = a.last_pass_collected_at
    try:
        return _main(a, host, read_key)
    finally:
        LAST_PASS_EXECSTART, LAST_PASS_COLLECTED_AT = prior   # never leaks into a later call without the flag


def _main(a, host, read_key):
    fp_key = None
    if a.fp_key_tty:
        try:
            fp_key = R.load_fp_key(read_key())
        except ValueError as e:
            print(f"collect-review-evidence: {e}", file=sys.stderr)
            return 2
    if not (a.fingerprint_only or a.credentials_only or a.other_journals) and fp_key is None:
        print("collect-review-evidence: the full bundle needs --fp-key-tty (Option B §8: keyed cid fingerprints)",
              file=sys.stderr)
        return 2
    host = host or Host()
    try:
        ctx = context(host, fp_key)
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
            other, other_secrets, other_failed = other_credentials(host)
            if other_failed:
                raise CouldNotCheck("; ".join(other_failed))
        except CouldNotCheck as e:
            print(f"collect-review-evidence: {e} — refusing to certify the installed set",
                  file=sys.stderr)
            return 2
        if unparsed or unreadable:
            print(f"collect-review-evidence: {len(unparsed)} unparsed and {len(unreadable)} "
                  "unreadable credential-shaped file(s) found — refusing to certify the "
                  "installed set", file=sys.stderr)
            return 2
        out, secrets = R.credential_set(infos) + other, secrets + other_secrets
    elif a.other_journals:
        try:
            infos, secrets, unparsed, unreadable = installed_credentials(host)
            other, other_secrets, other_failed = other_credentials(host)
            if other_failed or unparsed or unreadable:
                raise CouldNotCheck("the installed secret values could not all be loaded")
            secrets = secrets + other_secrets
            out = {"schema": 1, "kind": "other-journals", "collected_at": R.utc_now(),
                   **other_journals(host, ctx, secrets)}
        except (CouldNotCheck, OSError, ValueError) as e:
            reason = str(e) if isinstance(e, CouldNotCheck) else type(e).__name__
            print(f"collect-review-evidence: other journals: {reason}", file=sys.stderr)
            return 2
    else:
        out, secrets, _ = _collect(host, fp_key)
    secrets = secrets + ([fp_key.hex()] if fp_key else [])
    # Twice: on the text as collected, then on the text to print. The redactor rewrites a client
    # slug or a customer id INSIDE a secret value, so the redacted text alone would let the rest
    # of that value through.
    R.assert_no_secret(json.dumps(out, indent=2, sort_keys=True), secrets)
    text = json.dumps(ctx["redactor"].obj(out), indent=2, sort_keys=True)
    R.assert_no_secret(text, secrets)
    if not R.restrict_output(sys.stdout):
        print("collect-review-evidence: the output file could not be made owner-only: nothing written",
              file=sys.stderr)
        return 2
    print(text)
    return rc


if __name__ == "__main__":
    sys.exit(main())
