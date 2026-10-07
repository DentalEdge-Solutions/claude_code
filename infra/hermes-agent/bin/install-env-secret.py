#!/usr/bin/env python3
"""Install or strip ONE secret in an env file (Option B §6, BRING-UP). Stdlib only.

  sudo install-env-secret.py set      --file F --name N --prefix P --mode 0400|0600 [--quote single] [--stdin] [--owner-uid U --owner-gid G]
  sudo install-env-secret.py generate --file F --name N --mode 0400|0600 [--owner-uid U --owner-gid G]
  sudo install-env-secret.py strip    --file F --name N

`set` reads the value from /dev/tty with echo off (never argv, never stdin of a paste), refuses
a value without the expected prefix, and replaces or appends the one NAME= line. Every other
line is kept byte-for-byte. The new file is written beside the old one (O_EXCL), fsync'd, given
its owner and mode on the fd, and renamed over it: a governed file is never half-written, and a
bad input never replaces a good file (the 2026-09-30 registry lesson). Never prints a value.

`--quote single` writes NAME='value', for a value that holds `$`: Docker Compose interpolates `$`
in an env_file, and a dashboard password hash (`scrypt$16384$8$1$<salt>$<hash>`) written bare
reaches the container cut short, with only a warning (measured 2026-10-07, finding F52). Inside
single quotes Compose takes the value literally. So `set` refuses a value with `$` unless it is
quoted, and refuses a single quote inside a quoted value.

`--stdin` takes the value from a PIPE instead of the terminal, for a value another program
makes (the hash, computed inside the gateway container): `... | install-env-secret.py set ...
--stdin`. It refuses a terminal on stdin, so it can never be the target of a paste, and it drops
one trailing line break. The value still never touches argv, a file or the screen.

`generate` makes the value itself: 32 random bytes, base64 (the form `openssl rand -base64 32`
gives), for a secret nobody needs to know, such as the dashboard's session-signing key. It never
leaves the file: nothing is typed, pasted or printed. It refuses a name that already has a
value; `strip` it first to replace it."""
import argparse, base64, getpass, os, re, stat, sys, warnings

NAME_RE = re.compile(r"^[A-Z][A-Z0-9_]{0,63}$")


def _tty_value():
    # getpass silently falls back to echoing stdin (GetPassWarning) when /dev/tty or echo control
    # is unavailable; turn that into "no value" so the tool refuses instead.
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", getpass.GetPassWarning)
            return getpass.getpass("value (hidden): ")
    except (EOFError, OSError, getpass.GetPassWarning):
        return None


def _lines(path):
    try:
        st = os.lstat(path)
    except FileNotFoundError:
        return [], None
    if stat.S_ISLNK(st.st_mode) or not stat.S_ISREG(st.st_mode):
        raise ValueError(f"{path} is a symlink or not a regular file")
    # newline="" + split on "\n" only: CRLF, \x0c etc. in other lines survive byte-for-byte.
    with open(path, encoding="utf-8", errors="surrogateescape", newline="") as f:
        return _split(f.read()), st


def _split(text):
    return re.findall(r"[^\n]*\n|[^\n]+", text)


def _is_assign(line, name):
    s = line.lstrip(" \t")
    if s.startswith("export "):
        s = s[len("export "):].lstrip(" \t")
    return s.startswith(name + "=")


def _write_all(fd, data):
    view = memoryview(data); total = 0
    while total < len(data):
        n = os.write(fd, view[total:])
        if not n or n < 0:
            raise OSError("short write: no progress")
        total += n
    if total != len(data):
        raise OSError("short write")


def _write(path, lines, mode, uid, gid):
    data = "".join(lines).encode("utf-8", "surrogateescape")
    d = os.path.dirname(os.path.abspath(path))
    tmp = os.path.join(d, ".%s.%d.tmp" % (os.path.basename(path), os.getpid()))
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        try:
            _write_all(fd, data)
            os.fsync(fd)
            if uid is not None:
                os.fchown(fd, uid, gid)
            os.fchmod(fd, mode)
        finally:
            os.close(fd)                                  # exactly once
        os.rename(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _pipe_value():
    """The value from stdin when stdin is a pipe or a file, without one trailing line break; None
    when stdin is a terminal (a paste is what the hidden prompt is for) or cannot be read."""
    try:
        if sys.stdin.isatty():
            return None
        v = sys.stdin.read()
    except (OSError, ValueError, UnicodeDecodeError):
        return None
    return v[:-1] if v.endswith("\n") else v


def main(argv=None, read_value=_tty_value, random_bytes=os.urandom, read_pipe=_pipe_value):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    s, g = sub.add_parser("set"), sub.add_parser("generate")
    for p in (s, g, sub.add_parser("strip")):
        p.add_argument("--file", required=True)
        p.add_argument("--name", required=True)
    s.add_argument("--prefix", required=True)
    s.add_argument("--quote", choices=("single",))
    s.add_argument("--stdin", action="store_true")
    for p in (s, g):
        p.add_argument("--mode", required=True, choices=("0400", "0600"))
        p.add_argument("--owner-uid", type=int)
        p.add_argument("--owner-gid", type=int)
    a = ap.parse_args(argv)
    try:
        if a.cmd == "set" and not a.prefix:
            raise ValueError("refused: --prefix must not be empty")
        if not NAME_RE.match(a.name):
            raise ValueError("invalid variable name")
        lines, st = _lines(a.file)
        kept = [l for l in lines if not _is_assign(l, a.name)]
        if a.cmd == "strip":
            if st is None:
                print(f"install-env-secret: {a.file} absent; nothing to strip"); return 0
            _write(a.file, kept, stat.S_IMODE(st.st_mode), st.st_uid, st.st_gid)
            print(f"install-env-secret: {a.name} removed from {a.file} ({len(lines) - len(kept)} line(s))")
            return 0
        if a.cmd == "generate":
            if any(_is_assign(l, a.name) and l.split("=", 1)[1].strip() for l in lines):
                raise ValueError(f"refused: {a.name} already has a value in {a.file}; strip it first to replace it")
            v, quote = base64.b64encode(random_bytes(32)).decode("ascii"), None
        else:
            v, quote = (read_pipe() if a.stdin else read_value()), a.quote
            if not v or "\n" in v or "\r" in v or not v.startswith(a.prefix):
                raise ValueError(f"refused: the value is empty, multi-line, or does not start with {a.prefix!r}")
            try:
                v.encode("utf-8")                         # strict: no lone surrogates
            except UnicodeEncodeError:
                raise ValueError("refused: the value is not valid UTF-8 text") from None
            if quote is None and "$" in v:
                raise ValueError("refused: the value holds `$`, which Docker Compose would interpolate; "
                                 "write it with --quote single")
            if quote == "single" and "'" in v:
                raise ValueError("refused: a single-quoted value cannot hold a single quote")
        new = f"{a.name}='{v}'\n" if quote == "single" else f"{a.name}={v}\n"
        idx = next((i for i, l in enumerate(lines) if _is_assign(l, a.name)), None)
        if idx is None:                                   # append, keeping a final newline
            out = kept + ([] if not kept or kept[-1].endswith("\n") else ["\n"]) + [new]
        else:                                             # replace in place; drop any later duplicates
            out = [new if i == idx else l for i, l in enumerate(lines)
                   if i == idx or not _is_assign(l, a.name)]
        uid = a.owner_uid if a.owner_uid is not None else (st.st_uid if st else None)
        gid = a.owner_gid if a.owner_gid is not None else (st.st_gid if st else None)
        _write(a.file, out, int(a.mode, 8), uid, gid)
        print(f"install-env-secret: {a.name} {'generated' if a.cmd == 'generate' else 'set'} in {a.file} (mode {a.mode})")
        return 0
    except (ValueError, OSError) as e:
        print(f"install-env-secret: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
