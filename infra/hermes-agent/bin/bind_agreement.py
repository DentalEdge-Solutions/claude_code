"""F9: the strings Compose sends as ads-mutator's HostConfig.Binds, computed without Docker,
and the values the two systemd units pin.

Stdlib only: the proxy may not grow a dependency, so neither may its guard. Used by
proxy-policy-sync.test.py (static, every platform) and
deploy/bind-agreement-integration.test.py (real Docker, Linux CI), which also checks this
model against real Compose on every run.

THE MODEL (measured, spec §2): Compose v2 sends an ABSOLUTE source verbatim — no symlink
resolution, no cleaning (M2) — and gives a bare entry the mode "rw" (M3). A RELATIVE source is
joined to a project directory whose spelling depends on how Compose was started (-f form, PWD,
sudo: M1, M6). That dependence is F9 itself, so a relative source is refused here rather than
guessed at.

Only two interpolation forms are actually implemented: bare `${VAR}` and the guarded
`${VAR:?msg}`. Every other form — `${VAR:-default}`, `${VAR?err}`, a bare unbraced `$VAR` — is
deliberately left literal rather than interpolated, so it fails closed: either as a "relative
bind source" (it does not start with `/`) or as a mismatch against the pins. A `}` inside a
guard message will also mis-parse, since `${VAR:?msg}` is matched up to the first `}`.
"""
import re
import shlex

_VAR = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(:\?([^}]*))?\}")
_MASK = re.compile(r"\x00(\d+)\x00")


class Unresolved(ValueError):
    """A ${VAR:?msg} whose VAR is unset or empty: Compose would stop with msg."""


def interpolate(text, env):
    def sub(m):
        name, guard, msg = m.group(1), m.group(2), m.group(3)
        val = env.get(name, "")
        if guard and not val:
            raise Unresolved("%s: %s" % (name, msg or "required"))
        return val
    return _VAR.sub(sub, text)


def _mask(text):
    """Hide every ${...} (which may hold ':', ' ', ',' or '#') behind a placeholder."""
    found = []

    def hide(m):
        found.append(m.group(0))
        return "\x00%d\x00" % (len(found) - 1)
    return _VAR.sub(hide, text), (lambda s: _MASK.sub(lambda m: found[int(m.group(1))], s))


def split_volume(entry):
    masked, unmask = _mask(entry)
    parts = [unmask(p) for p in masked.split(":")]
    if len(parts) not in (2, 3):
        raise ValueError("not a short-form volume entry: %r" % entry)
    return parts[0], parts[1], (parts[2] if len(parts) == 3 else None)


def service_block(compose_text, service):
    marker = "\n  %s:\n" % service
    start = compose_text.find(marker)
    if start < 0:
        raise ValueError("service %r not found in the compose file" % service)
    rest = compose_text[start + 1:]
    m = re.search(r"\n  [A-Za-z0-9_-]+:\n", rest)
    return rest[:m.start()] if m else rest


def service_volumes(compose_text, service):
    out, inside = [], False
    for line in service_block(compose_text, service).splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        indent = len(line) - len(line.lstrip())
        if indent == 4 and stripped == "volumes:":
            inside = True
            continue
        if not inside:
            continue
        if indent <= 4:
            break
        if stripped.startswith("- "):
            masked, unmask = _mask(stripped[2:])
            out.append(unmask(re.split(r"\s+#", masked, maxsplit=1)[0].strip()))
    return out


def compose_binds(compose_text, env, service="ads-mutator"):
    out = []
    for entry in service_volumes(compose_text, service):
        src, dst, mode = split_volume(entry)
        src = interpolate(src, env)
        if not src.startswith("/"):
            raise ValueError(
                "relative bind source %r (from %r): its string depends on how Compose was "
                "invoked (spec §2, M1/M6), so it cannot be pinned" % (src, entry))
        out.append("%s:%s:%s" % (src, dst, mode or "rw"))
    return out


def _directives(unit_text):
    joined = re.sub(r"\\\n", " ", unit_text)
    return [l.strip() for l in joined.splitlines()
            if l.strip() and not l.strip().startswith(("#", ";"))]


def unit_exec_args(unit_text):
    """ExecStart tokens after the FIRST token only.

    For /path/to/program --flags, returns ['--flags'].
    For /usr/bin/interpreter /path/to/script --flags, returns ['/path/to/script', '--flags'].
    The only caller needing flags is the proxy unit (docker-create-proxy.service).
    allow_binds is unaffected because it selects by flag name.
    """
    for line in _directives(unit_text):
        if line.startswith("ExecStart="):
            return shlex.split(line[len("ExecStart="):])[1:]
    raise ValueError("the unit has no ExecStart=")


def unit_environment(unit_text):
    env = {}
    for line in _directives(unit_text):
        if line.startswith("Environment="):
            key, _, val = line[len("Environment="):].partition("=")
            env[key] = val
    return env


def allow_binds(unit_text):
    args = unit_exec_args(unit_text)
    return [args[i + 1] for i, a in enumerate(args) if a == "--allow-bind" and i + 1 < len(args)]
