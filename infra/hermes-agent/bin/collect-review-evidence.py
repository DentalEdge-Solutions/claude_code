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
import argparse, ast, base64, calendar, datetime, fnmatch, getpass, grp, json, os, pwd, re, shlex, stat, subprocess, sys, time
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


def _run_real(argv, timeout=60):
    try:
        p = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
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
                     "permitopen": re.compile(r"(127\.0\.0\.1|localhost|\[::1\]):(\d{1,5}|\*)"),
                     "permitlisten": re.compile(r"((127\.0\.0\.1|localhost|\[::1\]):)?(\d{1,5}|\*)")}


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


def _key_row(line):
    """One authorized_keys line as its key type, its options and a short fingerprint of the key
    body, or None when it is not a key line. The body and the comment are never returned."""
    tokens, unbalanced = _split_unquoted(line.strip(" \t"), " \t")      # sshd skips only spaces and tabs
    if unbalanced:
        return None
    for i in (0, 1):                                    # the key type is first, or second after the options
        if len(tokens) > i + 1 and _KEY_TYPE_RE.fullmatch(tokens[i]) and _KEY_BODY_RE.fullmatch(tokens[i + 1]):
            try:
                body = base64.b64decode(tokens[i + 1], validate=True)
            except ValueError:
                return None
            options = _split_unquoted(tokens[0], ",")[0] if i == 1 else []
            return {"type": tokens[i], "options": sorted(_shown_option(o) for o in options),
                    "sha12": PK.sha256_bytes(body)[:12]}
    return None


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
        if not line.strip(" \t") or line.lstrip(" \t").startswith("#"):
            continue
        key = _key_row(line)
        if key is None:
            unparsed += 1
        else:
            keys.append(key)
    return {**row, "keys": keys, "unparsed_lines": unparsed}


def _unprivileged_port_start(host):
    """The first port an account without privileges may bind, as the kernel states it (a host's
    default is 1024). Anything that is not one port number is could-not-check."""
    try:
        with open(host.path(UNPRIVILEGED_PORT_START)) as f:
            text = f.read().strip()
    except OSError:
        return R.COULD_NOT_CHECK
    if not re.fullmatch(r"\d{1,5}", text) or int(text) > 65535:
        return R.COULD_NOT_CHECK
    return int(text)


def d1_7(host, ctx):
    """Every SSH key the box accepts, for EVERY account in /etc/passwd: an account with no login
    shell can still be used for a forward. Key types, options and short fingerprints only. The
    sshd settings are the global ones (`sshd -T`): a `Match` block is not read here (the
    fingerprint's entry_points component carries the whole of `sshd -T`). The kernel's
    net.ipv4.ip_unprivileged_port_start setting is read because the limited key's permitlisten
    depends on it."""
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
            parts = line.rstrip("\n").split(":")
            if len(parts) != 7:
                continue
            accounts += 1
            for p in _authorized_keys_paths(got["authorizedkeysfile"], parts[0], parts[5] or "/"):
                try:
                    os.lstat(host.path(p))
                except (FileNotFoundError, NotADirectoryError):
                    continue                # no such file: nothing accepts a key from it
                except OSError:
                    pass                    # cannot tell: keep the path, the row says so
                users_of.setdefault(p, set()).add(parts[0])
    return {"sshd": {k: got.get(k, R.COULD_NOT_CHECK) for k in SSHD_KEY_SOURCES},
            "accounts_checked": accounts,
            "unprivileged_port_start": _unprivileged_port_start(host),
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


def d2_3(host, ctx):
    return {"journal": _count_cred_text(_ok(host, ["journalctl", "-o", "cat", "--no-pager"]), ctx.get("secrets", []))}


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
_ISO_FORMAT = "%Y-%m-%dT%H:%M:%SZ"
_ISO_RE = re.compile(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ")
_SYSTEMD_TS_RE = re.compile(r"[A-Z][a-z]{2} (\d{4}-\d\d-\d\d) (\d\d:\d\d:\d\d) UTC")
_DOCKER_TS_RE = re.compile(r"(\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d)(\.\d+)?Z")
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
    except (OSError, SyntaxError, ValueError):
        return R.COULD_NOT_CHECK, R.COULD_NOT_CHECK


def d4_6(host, ctx):
    """When the host, Docker, the three long-running Hermes services and the gateway container
    last started, each compared with the last PASS's collection time (given with
    --last-pass-collected-at), and which files each service loads that changed after it
    started. D4.2's hash is the same string after any daemon-reload, so it cannot show a
    restart (review #8); this item can. Timestamps, unit names and file names only."""
    starts = {"boot": _boot_at(host), "docker": _unit_started_at(host, "docker"),
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


def _journal(host, unit):
    return _ok(host, ["journalctl", "-u", unit, "--since", "-30d", "-o", "cat", "--no-pager"])


def _journal_leaks(text, secrets, redactor):
    """What a unit's journal must hold none of: lines of Google-credential-shaped text, lines
    with a registered customer id, and (as D2.3 counts them) credential patterns and the
    installed secret values themselves. Counts only, never a line."""
    lines = text.splitlines()
    return {"credential_text_lines": sum(1 for l in lines if R.looks_like_credential_text(l)),
            "customer_id_lines": sum(1 for l in lines if redactor.has_customer_id(l)),
            **_count_cred_text(text, secrets)}


def d10_7(host, ctx):
    """Counts only, never a line: the journal names clients and request ids by design. The
    status/reason counts are the broker's; the leak counts cover the runner's journal too,
    which is where run-client-audit's own output lands (its unit sets no StandardOutput)."""
    broker = _journal(host, f"hermes-app-broker@{APP}")
    runner = _journal(host, f"hermes-app-runner@{APP}")
    counts, notes, other = {}, {}, 0
    for line in broker.splitlines():
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
    # The non-Google values are loaded before the probes; D2.1 (it runs first) adds the Google
    # ones and any other it finds. With none
    # loaded, known_secret_hits can only be 0: known_secrets_checked says how many were looked for.
    secrets = sorted({s for s in ctx.get("secrets", []) if len(s) >= 8})
    return {"journal_counts": counts, "note_counts": notes, "other_lines": other,
            "broker_journal": _journal_leaks(broker, secrets, ctx["redactor"]),
            "runner_journal": _journal_leaks(runner, secrets, ctx["redactor"]),
            "known_secrets_checked": len(secrets)}


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


PROBES = {"D1.1": d1_1, "D1.2": d1_2, "D1.3": d1_3, "D1.4": d1_4, "D1.5": d1_5, "D1.6": d1_6,
          "D2.1": d2_1, "D2.2": d2_2, "D2.3": d2_3,
          "D4.1": d4_1, "D4.2": d4_2, "D4.3": d4_3, "D4.4": d4_4, "D4.5": d4_5,
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
    if not (a.fingerprint_only or a.credentials_only) and fp_key is None:
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
    else:
        out, secrets, _ = _collect(host, fp_key)
    secrets = secrets + ([fp_key.hex()] if fp_key else [])
    # Twice: on the text as collected, then on the text to print. The redactor rewrites a client
    # slug or a customer id INSIDE a secret value, so the redacted text alone would let the rest
    # of that value through.
    R.assert_no_secret(json.dumps(out, indent=2, sort_keys=True), secrets)
    text = json.dumps(ctx["redactor"].obj(out), indent=2, sort_keys=True)
    R.assert_no_secret(text, secrets)
    print(text)
    return rc


if __name__ == "__main__":
    sys.exit(main())
