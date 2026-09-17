# Phase B Docker Endpoint Measurement (2026-09-16)

## Environment

- Date: 2026-09-16
- Host: Docker Desktop on darwin (macOS), NOT the VPS.
- Docker CLI/Engine (client): 29.7.2, API version 1.55 (`DefaultAPIVersion: 1.55`)
- Docker Engine (server, inside Docker Desktop VM): 29.7.2, `ApiVersion: 1.55`, Os: linux/arm64, Platform: Docker Desktop 4.88.1 (237512)
- Docker Compose: v5.4.0
- Compose file under test: `infra/hermes-agent/docker-compose.yml`
- Target service invoked: `ads-mutator` (profile `tools`), via `docker compose run --rm --no-deps -T ads-mutator --help`

## Method

A throwaway keep-alive-aware logging HTTP pass-through was written (NOT committed) at:
`/private/tmp/claude-501/-Users-ericksicard-Projects-claude-code/15332133-8d62-4ccf-ad4c-41b8df468c0f/scratchpad/hbproxy.py`

It listens on `/tmp/hbproxy.sock` (17 bytes — well under the ~104-byte AF_UNIX path cap) and
forwards to the real Docker socket at `/var/run/docker.sock`. Unlike a naive first-request-only
splice, it loops per-connection: parses the request line + headers, reads exactly
`Content-Length` bytes of body, logs, forwards, relays the full response (handling
`Content-Length`, chunked transfer-encoding, and zero-body responses), then loops for the next
request on the same connection. `/attach`-style requests (upgrade/hijack) are detected and the
connection is switched to a raw bidirectional pump instead of being parsed further.

`DOCKER_HOST=unix:///tmp/hbproxy.sock` was set only for the `docker compose run` invocation
against `ads-mutator`; `HERMES_GOVERNANCE_DIR` was a throwaway `mktemp -d` directory (never
`~/.hermes`), pre-populated with `approvals/ control/ registry/ log/`.

Before trusting the run, `docker ps -a` was checked for stale `ads-mutator` containers from
earlier attempts (per the brief's warning that a stale container can make `POST
/containers/create` never appear); none were present before the first run.

## A second trap, found while building the tool (not just the keep-alive one)

The brief's warned-about trap (first-request-only splicing) was avoided from the start by
writing the pass-through to loop. But the first working draft still failed differently, and it
is worth recording because it is a *second*, distinct failure mode in the same class of bug.

**Attempt 1 (lock-step per-connection loop):** parse request → forward → block reading *that
request's* response → only then read the next request on the connection. This looked correct
and handled simple keep-alive fine. Run through it, `docker compose run --rm --no-deps -T
ads-mutator --help` **hung and hit the 90s timeout (exit 124)**. The log showed why: call #9
`POST /containers/create` succeeded, three `GET .../json` inspects followed, then call #13 was
`POST .../wait?condition=removed` — which blocks server-side until the container exits and (with
`--rm`) is removed. My proxy, being lock-step, blocked reading *that* response before reading
anything else off the same connection. But the container was still in `Created` state — `POST
.../start` had not been sent yet. `docker ps -a` after the hang confirmed it: the container sat
in `Created`, never `Running`. The Docker client pipelines requests independently of when it
reads responses; my proxy's lock-step assumption made it deaf to a pipelined (or, in the
successful re-run, differently-scheduled) `start` request while it waited on `wait`'s response —
a self-inflicted deadlock. This is the same *shape* of bug the brief warns about (assuming request
handling and response handling are always paired 1:1 on a connection) even though it isn't the
literal keep-alive-splice trap.

**Fix (attempt 2, used for the measurement below):** decoupled request framing from response
relaying entirely. Per connection, two independent loops run concurrently: one reads and frames
HTTP requests off the client side, logs each one, and forwards its raw bytes to the real socket
*immediately*, without ever waiting for that request's response; a second is a pure raw
byte-pump from the real socket back to the client, running for the connection's whole lifetime,
unparsed. This makes pipelining and out-of-order request/response arrival irrelevant to
correctness. After the fix, the same command completed with **exit 0**.

The stale `Created`-state container left behind by the deadlocked attempt was removed
(`docker rm -f`) before re-running, per the brief's explicit warning that a leftover container
can make the next run's `POST /containers/create` never appear.

## Raw results

The fixed pass-through logged **15 HTTP requests across 3 connections** for one
`docker compose run --rm --no-deps -T ads-mutator --help` invocation — normalizing container IDs
and the one-off container name suffix, that is **10 distinct endpoints**, the same count as D1's
reference measurement (14 calls/10 endpoints, measured 2026-08-31 against a different Compose
version). The 15-vs-14 difference is one extra `HEAD /_ping` call (2 here vs. presumably 1 in
D1) — not a dropped-request signal; every endpoint category in D1's set is present here, plus the
same shape (repeated `containers/json` list calls, repeated post-create `containers/{id}/json`
inspects). Nothing indicates missed requests: the connection carrying the
differently-scheduled `start` and the one carrying `wait` both surfaced correctly, and the
`/attach` hijack was caught and degraded to raw relay rather than mis-parsed as a framed request.

### Endpoint list (normalized, with call counts)

| # | Method | Endpoint (container id and dynamic name normalized) | Connection | Calls |
|---|--------|-------------------------------------------------------|-----------|-------|
| 1 | HEAD | `/_ping` | conn1 | 2 |
| 2 | GET | `/v1.55/containers/json?all=1&filters={config-hash,project=hermes-agent}` | conn1 | 2 (calls #3, #7 — identical query) |
| 3 | GET | `/v1.55/networks?filters={project=hermes-agent}` | conn1 | 1 |
| 4 | GET | `/v1.55/volumes?filters={project=hermes-agent}` | conn1 | 1 |
| 5 | GET | `/v1.55/images/hermes-agent-claude/json?manifests=1` | conn1 | 1 |
| 6 | GET | `/v1.55/containers/json?all=1&filters={config-hash,oneoff=False,project=hermes-agent}` | conn1 | 1 (call #8 — distinct query from #2/#3/#7) |
| 7 | POST | `/v1.55/containers/create?name=hermes-agent-ads-mutator-run-{id}` | conn1 | 1 |
| 8 | GET | `/v1.55/containers/{id}/json` | conn1 | 3 (calls #10, #11, #12 — repeated inspect) |
| 9 | POST | `/v1.55/containers/{id}/attach?stderr=1&stdin=1&stdout=1&stream=1` | conn2 | 1 (upgrades to raw stream — not parsed further) |
| 10 | POST | `/v1.55/containers/{id}/wait?condition=removed` | conn1 | 1 |
| 11 | POST | `/v1.55/containers/{id}/start` | conn3 | 1 |

(Table has 11 rows because row 2 and row 6 are both base path `/containers/json` with different
query filters — counted as one "endpoint" in the 10-distinct-endpoint tally the way D1 counted,
by base path + method: `/_ping`, `/containers/json`, `/networks`, `/volumes`,
`/images/.../json`, `/containers/create`, `/containers/{id}/json`, `/containers/{id}/attach`,
`/containers/{id}/wait`, `/containers/{id}/start` = 10.)

Total calls: 2+2+1+1+1+1+1+3+1+1+1 = **15**.

Notable: `start` (call `conn3#1`) arrived on a **third, separate connection**, not pipelined
after `wait` on conn1 — confirming the earlier lock-step design's failure was a genuine
pipelining/connection-scheduling hazard in the Docker client's HTTP transport, not a fluke tied
to one specific ordering.

### Verbatim `POST /containers/create` body (pretty-printed)

No client names, customer ids, campaign ids, or credential values appeared in the body — it is
the `ads-mutator` bootstrap invocation (`--help`), not a live changeset apply, so there was
nothing to redact. Confirmed by grep against the raw captured body for
client/campaign/secret/token/key-shaped strings: no hits besides the (non-secret) env var name
`HERMES_GOVERNANCE_ROOT` and Compose's own `com.docker.compose.*` labels.

```json
{
  "Hostname": "",
  "Domainname": "",
  "User": "",
  "AttachStdin": true,
  "AttachStdout": true,
  "AttachStderr": true,
  "Tty": false,
  "OpenStdin": true,
  "StdinOnce": true,
  "Env": [
    "HERMES_GOVERNANCE_ROOT=/opt/governance"
  ],
  "Cmd": [
    "--help"
  ],
  "Image": "hermes-agent-claude",
  "Volumes": null,
  "WorkingDir": "",
  "Entrypoint": [
    "python3",
    "/opt/cc-bin/apply-changeset.py"
  ],
  "Labels": {
    "com.docker.compose.config-hash": "02e24b2fed441cd92cd67a4b25d758e55201424cafd5641e993f9218f523867f",
    "com.docker.compose.depends_on": "",
    "com.docker.compose.image": "sha256:d1dfc0a75e303596b9e4c7c1d3306fdac4df7a496f1acc83ab85a563810bf09b",
    "com.docker.compose.oneoff": "True",
    "com.docker.compose.project": "hermes-agent",
    "com.docker.compose.project.config_files": "/Users/ericksicard/Projects/claude_code/infra/hermes-agent/docker-compose.yml",
    "com.docker.compose.project.working_dir": "/Users/ericksicard/Projects/claude_code/infra/hermes-agent",
    "com.docker.compose.service": "ads-mutator",
    "com.docker.compose.slug": "9ef1cbd3ee2c7c9db39c0521036d5cc899380727883be3ce82cd594c6d55704b",
    "com.docker.compose.version": "5.4.0"
  },
  "HostConfig": {
    "Binds": [
      "/Users/ericksicard/Projects/claude_code/infra/hermes-agent/bin:/opt/cc-bin:ro",
      "/var/folders/g1/zg5wwl8j1rd0334q1vrdk_vm0000gn/T/tmp.N0HaDoSREp/approvals:/opt/governance/approvals:ro",
      "/var/folders/g1/zg5wwl8j1rd0334q1vrdk_vm0000gn/T/tmp.N0HaDoSREp/control:/opt/governance/control:ro",
      "/var/folders/g1/zg5wwl8j1rd0334q1vrdk_vm0000gn/T/tmp.N0HaDoSREp/registry:/opt/governance/registry:ro",
      "/var/folders/g1/zg5wwl8j1rd0334q1vrdk_vm0000gn/T/tmp.N0HaDoSREp/log:/opt/governance/log:rw",
      "/Users/ericksicard/Projects/claude-google-ads:/projects/claude_google_ads:ro",
      "/Users/ericksicard/Projects/claude_code/infra/hermes-agent/registry:/opt/registry:ro"
    ],
    "ContainerIDFile": "",
    "LogConfig": { "Type": "", "Config": null },
    "NetworkMode": "hermes-agent_default",
    "PortBindings": {},
    "RestartPolicy": { "Name": "", "MaximumRetryCount": 0 },
    "AutoRemove": true,
    "VolumeDriver": "",
    "VolumesFrom": null,
    "ConsoleSize": [0, 0],
    "CapAdd": null,
    "CapDrop": null,
    "CgroupnsMode": "",
    "Dns": null,
    "DnsOptions": null,
    "DnsSearch": null,
    "ExtraHosts": [],
    "GroupAdd": null,
    "IpcMode": "",
    "Cgroup": "",
    "Links": null,
    "OomScoreAdj": 0,
    "PidMode": "",
    "Privileged": false,
    "PublishAllPorts": false,
    "ReadonlyRootfs": false,
    "SecurityOpt": null,
    "UTSMode": "",
    "UsernsMode": "",
    "ShmSize": 0,
    "Isolation": "",
    "CpuShares": 0,
    "Memory": 0,
    "NanoCpus": 0,
    "CgroupParent": "",
    "BlkioWeight": 0,
    "BlkioWeightDevice": null,
    "BlkioDeviceReadBps": null,
    "BlkioDeviceWriteBps": null,
    "BlkioDeviceReadIOps": null,
    "BlkioDeviceWriteIOps": null,
    "CpuPeriod": 0,
    "CpuQuota": 0,
    "CpuRealtimePeriod": 0,
    "CpuRealtimeRuntime": 0,
    "CpusetCpus": "",
    "CpusetMems": "",
    "Devices": null,
    "DeviceCgroupRules": null,
    "DeviceRequests": null,
    "MemoryReservation": 0,
    "MemorySwap": 0,
    "MemorySwappiness": null,
    "OomKillDisable": false,
    "PidsLimit": null,
    "Ulimits": null,
    "CpuCount": 0,
    "CpuPercent": 0,
    "IOMaximumIOps": 0,
    "IOMaximumBandwidth": 0,
    "MaskedPaths": null,
    "ReadonlyPaths": null
  },
  "NetworkingConfig": {
    "EndpointsConfig": {
      "hermes-agent_default": {
        "IPAMConfig": null,
        "Links": null,
        "Aliases": ["hermes-agent-ads-mutator-run-9ef1cbd3ee2c"],
        "DriverOpts": null,
        "GwPriority": 0,
        "NetworkID": "",
        "EndpointID": "",
        "Gateway": "",
        "IPAddress": "",
        "MacAddress": "",
        "IPPrefixLen": 0,
        "IPv6Gateway": "",
        "GlobalIPv6Address": "",
        "GlobalIPv6PrefixLen": 0,
        "DNSNames": null
      }
    }
  }
}
```

Notable, not one of the four required questions but worth recording: `Env` carries only
`HERMES_GOVERNANCE_ROOT` — no `ANTHROPIC_API_KEY` or provider key is present, consistent with the
compose file's deliberate omission of `env_file: .env` on `ads-mutator`.

## The four required questions

**1. Does the create body carry a `User` field, and what is its value?**
**Yes — the key is present, and its value is the empty string `""`.** This matches the *substance*
of the design's prediction (no non-root user is being asserted at create time — `Dockerfile:38`'s
`USER hermes` takes effect at image-run-time, not via this field) but not the literal wording:
the field is not *absent*, it is present-but-empty. **Task 2's check must accept `User` being
either absent from the body or an empty string** — a check written as "field must not exist"
would break on real traffic, since the field measurably does exist here.

**2. `HostConfig.Binds` or `HostConfig.Mounts`?**
**`Binds`, and `Mounts` does not appear in the body at all** — not `null`, not an empty array, the
key is simply absent from the JSON. This was verified two ways: the pretty-printed body above,
and a raw grep for the literal string `"Mounts"` against the captured body, which found zero
matches. Compose behaves the same as the plain `docker` CLI here (contrary to the open question
in the brief that Compose "may differ") — **the design's blanket `Mounts`-block is safe to keep
for Compose-issued `ads-mutator` invocations**; it will not misfire against a key that isn't sent.

**3. The seven bind sources as resolved absolute paths:**
1. `/Users/ericksicard/Projects/claude_code/infra/hermes-agent/bin` → `/opt/cc-bin:ro`
2. `<mktemp-governance-dir>/approvals` → `/opt/governance/approvals:ro`
3. `<mktemp-governance-dir>/control` → `/opt/governance/control:ro`
4. `<mktemp-governance-dir>/registry` → `/opt/governance/registry:ro`
5. `<mktemp-governance-dir>/log` → `/opt/governance/log:rw`
6. `/Users/ericksicard/Projects/claude-google-ads` → `/projects/claude_google_ads:ro`
7. `/Users/ericksicard/Projects/claude_code/infra/hermes-agent/registry` → `/opt/registry:ro`

(`<mktemp-governance-dir>` was `/var/folders/g1/zg5wwl8j1rd0334q1vrdk_vm0000gn/T/tmp.N0HaDoSREp`
for this run — a throwaway `mktemp -d`, never the real `~/.hermes` store, substituted for
`${HERMES_GOVERNANCE_DIR}` by Compose's variable interpolation before the request was sent. In
production this resolves to whatever `HERMES_GOVERNANCE_DIR` is set to.) All three sources that
are relative in the compose file — `../../../claude-google-ads`, `./registry`, `./bin` — arrived
in the body already resolved to absolute paths by Compose, exactly as predicted; there is no
relative-path form to defend against at the proxy layer. The sibling project
`../claude-google-ads` referenced in the task brief resolves relative to the *repo root*
(`/Users/ericksicard/Projects/claude-google-ads`), consistent with all seven binds resolving with
no missing-path errors.

**4. What API version prefix appears?**
**`/v1.55/`** on every request that carries one (the two `HEAD /_ping` calls are unversioned, as
Docker's ping endpoint always is). Matches the client/server API version reported by `docker
version` (`ApiVersion: 1.55` on both Client and Server) and the value already observed
2026-09-16 while writing the plan.

## Environment version detail

```
Docker Client: 29.7.2 (API 1.55, GitCommit a7dcaa6, darwin/arm64)
Docker Server (Docker Desktop 4.88.1, linux/arm64 VM): 29.7.2 (API 1.55, GitCommit 6a43e3d)
Docker Compose: v5.4.0
```

## Cleanup performed

- The deadlocked first attempt's stale container (`hermes-agent-ads-mutator-run-6581c5e7ea1b`,
  stuck in `Created`) was force-removed (`docker rm -f`) before the successful re-run.
- The successful run's container was auto-removed (`AutoRemove: true` in the create body, `--rm`
  on the CLI); `docker ps -a --filter name=ads-mutator` was empty after the run completed.
- Both throwaway pass-through processes (the deadlocking v1 and the working v2) were killed and
  `/tmp/hbproxy.sock` removed. Nothing under `evals/telemetry` or the real `~/.hermes` governance
  store was touched — the governance dir used throughout was a `mktemp -d` throwaway.
- The pass-through script itself
  (`/private/tmp/claude-501/-Users-ericksicard-Projects-claude-code/15332133-8d62-4ccf-ad4c-41b8df468c0f/scratchpad/hbproxy.py`)
  is scratchpad-only and is not part of this commit.

---

*Measured under Docker Desktop on darwin. Per R22 this says nothing about the VPS; the
allow-list must be re-measured there before deploy.*
