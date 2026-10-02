#!/usr/bin/env python3
"""Pure helpers for run-client-audit.py (spec 2026-09-29 ads-audits-on-the-box). Stdlib only.
Nothing here prints; refusals raise PrecheckError with messages that never carry a customer id
or a credential value."""
import errno, fcntl, glob, os, re, shutil, stat
import package_lib as PK
import vault_lib as V


class PrecheckError(Exception):
    pass


class UnsafePathError(OSError):
    """A path component below a trusted base is a symlink, not a directory, or not a plain name.
    An OSError on purpose: under the lock the orchestrator maps OSError to rc 1 (PrecheckError
    there means the lock is held, rc 3)."""


def open_dir_below(base, parts):
    """An O_DIRECTORY fd for base/parts[0]/parts[1]/..., opened one component at a time with
    O_NOFOLLOW relative to the previous fd: a symlink planted at ANY component is refused, and
    no component can be swapped between a check and a use (F1). base itself is trusted (its
    parent is root-owned). Missing component: None. The caller closes the fd."""
    fd = os.open(base, os.O_RDONLY | os.O_DIRECTORY)
    try:
        for name in parts:
            if name in ("", ".", "..") or "/" in name:
                raise UnsafePathError(f"refusing path component {name!r}")
            try:
                nfd = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            except FileNotFoundError:
                return None
            except OSError as e:
                if e.errno in (errno.ELOOP, errno.ENOTDIR, errno.EMLINK):   # EMLINK: FreeBSD's ELOOP
                    raise UnsafePathError(f"{'/'.join(parts)}: {name!r} is a symlink or not a directory")
                raise
            os.close(fd)
            fd = nfd
        ret, fd = fd, None
        return ret
    finally:
        if fd is not None:
            os.close(fd)


def load_cred_env(path):
    """GOOGLE_ADS_* assignments, parsed as DATA (never sourced), matching run-ads-report.sh:
    split on the first '=', strip one layer of matching quotes, tolerate CRLF and `export `."""
    env = {}
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.rstrip("\r\n")
            if line.startswith("export "):
                line = line[len("export "):].lstrip()
            if not line.startswith("GOOGLE_ADS_") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
                v = v[1:-1]
            env[k] = v
    return env


def check_secret_file(path, uid=0, mode=0o400):
    try:
        st = os.stat(path)
    except FileNotFoundError:
        raise PrecheckError(f"{path} is missing")
    if st.st_uid != uid or stat.S_IMODE(st.st_mode) != mode:
        raise PrecheckError(f"{path} must be owner uid {uid}, mode {oct(mode)}; "
                            f"is uid {st.st_uid}, mode {oct(stat.S_IMODE(st.st_mode))}")


def anthropic_key_state(env_path):
    try:
        with open(env_path, encoding="utf-8") as f:
            for line in f:
                if line.startswith("ANTHROPIC_API_KEY="):
                    v = line.split("=", 1)[1].strip().strip("\"'")
                    if not v:
                        return "missing"
                    return "real" if v.startswith("sk-ant-") else "dummy"
    except FileNotFoundError:
        pass
    return "missing"


def eligible_client(slug, registry_path):
    try:
        V.validate_slug(slug)
    except ValueError:
        raise PrecheckError("invalid client slug")
    clients = V.load_registry(registry_path)
    if slug not in clients:
        raise PrecheckError(f"client {slug!r} is not registered")
    rec = dict(clients[slug])
    if rec.get("status") != "active":
        raise PrecheckError(f"client {slug!r} is {rec.get('status', 'unknown')}, not active")
    # Exactly ten digits, as a string: vault-write's validate_customer_id rejects dashes and
    # non-strings, and it runs LAST, after the spend. Refuse here instead (M7).
    cid = rec.get("customer_id")
    if not isinstance(cid, str) or not re.fullmatch(r"[0-9]{10}", cid):
        raise PrecheckError(f"client {slug!r} has no valid customer id in the registry "
                            "(exactly 10 digits, no dashes)")
    rec.update(slug=slug, customer_id=cid)
    return rec


def package_matches(app_dir, pin_sha256):
    mpath = os.path.join(app_dir, PK.MANIFEST_NAME)
    try:
        with open(mpath, "rb") as f:
            raw = f.read()
    except FileNotFoundError:
        raise PrecheckError("no installed app package")
    if PK.sha256_bytes(raw) != pin_sha256:
        raise PrecheckError("installed app package does not match its pin")
    for e in PK.load_manifest(raw)["files"]:
        p = os.path.join(app_dir, e["path"])
        if not os.path.isfile(p) or PK.sha256_file(p) != e["sha256"]:
            raise PrecheckError(f"installed file differs from the package: {e['path']}")


def reset_dir(path, uid=10000, gid=10000, mode=0o700):
    if os.path.lexists(path):
        shutil.rmtree(path)
    os.makedirs(path)
    os.chown(path, uid, gid)
    os.chmod(path, mode)


def error_files(path):
    return sorted(os.path.basename(p) for p in glob.glob(os.path.join(path, "*.ERROR.txt")))


def json_count(path):
    """Regular files only (lstat): a container-planted symlink named x.json is not data."""
    return sum(1 for p in glob.glob(os.path.join(path, "*.json")) if stat.S_ISREG(os.lstat(p).st_mode))


def others_named(text, me, slugs):
    low = text.lower()
    return sorted(s for s in slugs if s != me and re.search(r"(?<![\w-])" + re.escape(s.lower()) + r"(?![\w-])", low))


class AuditLock:
    def __init__(self, path):
        self.path, self.fd = path, None

    def __enter__(self):
        self.fd = os.open(self.path, os.O_RDWR | os.O_CREAT, 0o600)
        try:
            fcntl.flock(self.fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as e:
            os.close(self.fd)
            if e.errno in (errno.EAGAIN, errno.EACCES):
                raise PrecheckError("another audit is running")
            raise
        return self

    def __exit__(self, *exc):
        fcntl.flock(self.fd, fcntl.LOCK_UN)
        os.close(self.fd)


TS_RE = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}_[0-9]{2}-[0-9]{2}-[0-9]{2}$")
_AUDIT_NAME_RE = re.compile(r"^([0-9]{4}-[0-9]{2}-[0-9]{2}_[0-9]{2}-[0-9]{2}-[0-9]{2})-audit\.md$")


_COMMENT_RE = re.compile(r"\s+#.*")


_LINE_END_RE = re.compile(r"\r\n|\r|\n")      # the line ends a text-mode read of a file gives


def _env_value(v):
    """The value part of NAME=value, without the whitespace around it. A quoted value ends at its
    closing quote when nothing or only a comment follows; otherwise one layer of matching outer
    quotes is stripped, as before; otherwise the text is the value as it stands. An unquoted value
    ends at the first whitespace that is followed by `#` (a `#` with nothing before it is data)."""
    s = v.strip()
    if s[:1] in ("\"", "'"):
        end = s.find(s[0], 1)
        if end > 0 and (not s[end + 1:] or _COMMENT_RE.fullmatch(s[end + 1:])):
            return s[1:end]
        return s[1:-1] if len(s) >= 2 and s[0] == s[-1] else s
    return _COMMENT_RE.sub("", v, count=1).strip()


def _env_values(lines, name):
    """The value of each NAME= line among `lines`, in order, empty ones included."""
    for line in lines:
        line = line.rstrip("\r\n")
        if line.startswith("export "):
            line = line[len("export "):].lstrip()
        if line.startswith(name + "="):
            yield _env_value(line.split("=", 1)[1])


def load_env_value(path, name):
    """One NAME=value from an env file (the FIRST such line; None when there is none), parsed as
    DATA with load_cred_env's rules, plus an inline comment and surrounding whitespace (see
    _env_value): the installed files have neither today, but a hand edit must not turn a comment
    or a trailing blank into part of a key."""
    with open(path, encoding="utf-8") as f:
        return next(_env_values(f, name), None)


def env_values(text, name):
    """Every non-empty value NAME is given in env-file TEXT, in file order, parsed with
    load_env_value's rules. For a caller that must know every value a reader of this file
    might use, whichever line that reader prefers."""
    return [v for v in _env_values(_LINE_END_RE.split(text), name) if v]


def check_host_parent(path, uid=0, mode=0o711):
    """A host parent like /var/lib/hermes/vaults: a real directory, owned by root, exactly
    0711 — traversable by uid 10000, listable and renamable by root only."""
    try:
        st = os.lstat(path)
    except FileNotFoundError:
        raise PrecheckError(f"{path} is missing; create it root:root {oct(mode)}")
    if stat.S_ISLNK(st.st_mode) or not stat.S_ISDIR(st.st_mode):
        raise PrecheckError(f"{path} is a symlink or not a directory")
    if st.st_uid != uid or stat.S_IMODE(st.st_mode) != mode:
        raise PrecheckError(f"{path} must be owner uid {uid}, mode {oct(mode)}; "
                            f"is uid {st.st_uid}, mode {oct(stat.S_IMODE(st.st_mode))}")


def check_client_dir(path, uid):
    try:
        st = os.lstat(path)
    except FileNotFoundError:
        raise PrecheckError(f"{path} is missing; register the client's vault first")
    if stat.S_ISLNK(st.st_mode) or not stat.S_ISDIR(st.st_mode):
        raise PrecheckError(f"{path} is a symlink or not a directory")
    if st.st_uid != uid:
        raise PrecheckError(f"{path} must be owned by uid {uid}; is uid {st.st_uid}")


def list_audit_ts(dir_fd):
    out = []
    for name in os.listdir(dir_fd):
        m = _AUDIT_NAME_RE.match(name)
        if m and stat.S_ISREG(os.stat(name, dir_fd=dir_fd, follow_symlinks=False).st_mode):
            out.append(m.group(1))
    return sorted(out)
