"""The gateway container's listening TCP ports, read from its /proc/net/tcp and /proc/net/tcp6.

One parser for two readers: the security review's D4.1 (collect-review-evidence.py) and the
periodic check between reviews (check-gateway-listeners.py, finding F50). Only ports and one
count leave this module: no address and no other field of a row. Stdlib only.
"""
import re

GATEWAY_FILTER = "label=com.docker.compose.service=hermes-agent"
# What may listen in the gateway container: the dashboard, when it is switched on. Port 8642 (the
# API server Hermes v0.21.5 starts by default, F44) is deliberately not here.
ALLOWED_PORTS = (9119,)
_ROW_RE = re.compile(r"\d+:\s+([0-9A-Fa-f]+):([0-9A-Fa-f]{4})\s+[0-9A-Fa-f]+:[0-9A-Fa-f]{4}\s+([0-9A-Fa-f]{2})\s")
# Docker's embedded DNS resolver, on 127.0.0.11 with an ephemeral TCP port in every user-defined
# (Compose) network, as /proc/net/tcp spells the address and as tcp6 spells it IPv4-mapped.
DOCKER_DNS_ADDRS = ("0B00007F", "0" * 16 + "FFFF0000" + "0B00007F")
PROC_TABLES = ("/proc/net/tcp", "/proc/net/tcp6")
# Known limits of judging by port number (findings document, with F50): another program listening
# on an allowed port passes; anything bound to Docker's DNS address is counted as the resolver,
# whatever it is; UDP and unix sockets are not in these tables.


def parse(text):
    """(ports, docker_dns) from the two tables printed one after the other. `ports`: the sorted,
    distinct local ports (decimal) of every socket in state 0A (LISTEN), except those bound to
    Docker's embedded DNS address, which are only counted: `docker_dns`. Raises ValueError when
    the text is not exactly two tables (two header lines), or when any row does not parse."""
    headers, ports, dns = 0, set(), 0
    for line in text.splitlines():
        if not line.strip():
            continue
        if line.split()[0] == "sl":
            headers += 1
            continue
        m = _ROW_RE.match(line.strip())
        if not m or not headers:
            raise ValueError("a row of /proc/net/tcp did not parse")
        if m.group(3).upper() == "0A":
            if m.group(1).upper() in DOCKER_DNS_ADDRS:
                dns += 1
            else:
                ports.add(int(m.group(2), 16))
    if headers != 2:
        raise ValueError("expected exactly two tables")
    return sorted(ports), dns
