# VPS provisioning and bring-up: design

> **Written 2026-09-18.** Brainstormed against the tree at `e1c411b`, at the operator's
> request, after a session pointed at
> `docs/superpowers/handoffs/2026-09-17-vps-deploy-and-remeasurement.md` could not start:
> **no VPS exists yet.** That handoff assumes a provisioned host. This document specifies
> the work that has to happen before its §1 can run.
>
> **This is a NEW subsystem, not an amendment.** It supersedes Task 1–2 of the archived
> `docs/superpowers/plans/archive/2026-07-20-hermes-h3-vps-deploy.md`, whose `provision.sh`
> sketch was never built and which §3 below shows is unsafe as written. Where this document
> and that archived plan disagree, this document wins.
>
> Every measurement is stated with what produced it, and every inference is labelled as an
> inference. Per **R22**, nothing measured on darwin says anything about the VPS.

## 1. What this provisions, and what it deliberately does not

The deliverable — script plus runbook together — takes a bare Hostinger KVM 2 box to the
state `infra/hermes-agent/README.md:957` step 1 already assumes: a hardened Ubuntu 24.04 host
with Docker Engine, a non-root deploy account, and the on-box filesystem layout the systemd
units require. It stops there.

The two halves divide cleanly, and the split is the design: **`provision.sh` produces a
hardened host and knows nothing about Hermes**; **the runbook produces the layout** (§5 phase
2) and sequences everything else. A script that knew both would have to carry the repo paths,
the governance root and the reserved group names, which is what makes a security-relevant
script hard to review and unsafe to re-run.

**It does not** create the Hermes users and groups, lay out the governance store, install the
units, or start anything. `README.md:957` steps 1–5 own that sequence, it is merged and its
order was measured, and duplicating it into a script would create two sources of truth that
drift. The runbook sequences the two; it does not absorb one into the other.

**It does not enable mutation.** No kill switch is created at any point. The bring-up runs
with dummy credentials throughout, which is also what the archived H3 design requires: real
money-spending credentials go on the box only after a security-review gate that is downstream
of everything here.

## 2. Three findings that drive the design

### 2.1 The archived sketch's default deploy user would silently break the executor

The archived plan defaults `DEPLOY_USER=hermes` and runs `adduser hermes`. On Ubuntu that
also creates a **group** named `hermes`, at the next free gid. `README.md:957` step 1 then
runs:

```
getent group hermes >/dev/null || sudo groupadd -g 10000 hermes
```

The guard finds a group named `hermes` already present, skips, and **gid 10000 is never
created**. `usermod -aG hermes hermes-broker` puts the broker in the wrong gid, while the
governance store is `chgrp -R 10000` and the executor runs `USER hermes` at uid/gid 10000
(`Dockerfile`). The store is then unreadable to the executor: the kill switch reads as absent,
client resolution raises, and `append_log` fails *mid-apply* — exit 3 after a live account
change has landed. `README.md:894` documents that exact failure for the inverse case.

**This is an inference, not a measurement.** It follows from `adduser`'s documented
private-group behaviour and from the literal text of the step-1 guard; no Ubuntu host has been
observed doing it. It is cheap to make impossible and expensive to discover on a live apply,
so the design refuses the collision rather than relying on the operator reading the guard
carefully. §5 phase 1 measures it on the real box regardless.

### 2.2 The units dictate an on-box layout that no document states

`hermes-docker-proxy.service` and `hermes-broker.service` hardcode the filesystem:

| Path | Role | Asserted at |
|---|---|---|
| `/opt/hermes-agent` | `WorkingDirectory`; holds `bin/`, `registry/`, `data/spool` | `hermes-broker.service:17,22,27,29` · `hermes-docker-proxy.service:26,37,38` |
| `/var/lib/hermes/governance` | the governance store | `hermes-broker.service:20,21,28,36` · `hermes-docker-proxy.service:32-35` |
| `/opt/projects/claude-google-ads` | the ads repo | `hermes-docker-proxy.service:36` |

Neither `README.md:957` nor the handoff states any of it, and `.env.example` still carries the
placeholder `HERMES_GOVERNANCE_DIR=/absolute/path/to/.hermes/governance`. An operator who
follows the documented sequence and picks their own governance path gets a proxy that denies
the mutator's binds — fail-closed, but diagnosed as a broken rail rather than as a path
mismatch. The runbook states the layout as a table and the `.env.example` placeholder is
corrected (§6).

### 2.3 The compose bind paths and the allow-list may not be mutually satisfiable

`docker-compose.yml` mounts the ads repo as `../../../claude-google-ads`, resolved from the
compose file's own directory, and mounts `./registry` and `./bin`. The proxy compares bind
sources against `--allow-bind` as strings.

For `../../../claude-google-ads` to land on the allow-listed
`/opt/projects/claude-google-ads`, the compose directory must be
`/opt/projects/<repo>/infra/hermes-agent`. But the units say the compose directory **is**
`/opt/hermes-agent`, which would make `./registry` resolve to
`/opt/projects/<repo>/infra/hermes-agent/registry` rather than the allow-listed
`/opt/hermes-agent/registry`. Those are different strings.

Whether a symlink reconciles them depends on whether Compose canonicalises the project
directory before sending bind sources to the Docker API. **That is not determined here, and
must not be guessed** — reasoning about how a dependency resolves paths is the precise shape
of assumption this project has paid for repeatedly. §5 phase 5 measures the actual bind
sources and diffs them against the allow-list.

**Resolution is out of scope for this deliverable.** On a mismatch the runbook stops and
records a finding for its own wave. Widening the allow-list to make bring-up pass is the same
reflex the handoff's §3 and §5 name explicitly, and a rail that refuses is a refusal, not a
breach.

## 3. `deploy/provision.sh`

Idempotent, `set -euo pipefail`, run as root on a fresh box. Knows nothing about Hermes except
which names it must refuse. Six departures from the archived sketch, each because the sketch
is wrong or unsafe on this host:

| Archived sketch | This design | Why |
|---|---|---|
| `DEPLOY_USER=hermes` | default `hermesops`; hard refuse `hermes`, `hermes-broker`, `hermes-docker-proxy`, `hermes-rail` | §2.1 |
| `usermod -aG docker "$DEPLOY_USER"` | omitted; deploy user is added to `sudo` only | §3.1 |
| `sed -i` against `/etc/ssh/sshd_config` | drop-in `/etc/ssh/sshd_config.d/10-hermes-hardening.conf`, `sshd -t` validated, then `reload` | §3.2 |
| `echo "$SSH_PUBKEY" > authorized_keys` | `grep -qxF` then append | `>` destroys every other key on the box, including on re-run |
| `ufw --force reset` before configuring | converge only: defaults, `allow OpenSSH`, `--force enable` | `reset` drops every rule mid-run; on a re-run that is a window with no firewall |
| `curl -fsSL https://get.docker.com \| sh` | Docker's apt repository with the signing key installed to a keyring | §3.3 |

### 3.1 The deploy user is not in the `docker` group

Operator decision, 2026-09-18. Deploy commands run under `sudo`.

**This is not a claim that `sudo` is less powerful than `docker`** — both are root-equivalent,
and saying otherwise would be security theatre. Three things are actually bought:

1. `sudo` is logged; `docker` group membership is a silent, unlogged path to root.
2. The box grows exactly one root-equivalent admin identity instead of two, one of which does
   not look like one.
3. `getent group docker` becomes a meaningful check on the real host. `units.test.py` asserts
   the broker is not in `docker` in the unit *files*; keeping the deploy user out means the
   same invariant is true of the running box, so §5 can verify `hermes-docker-proxy` is the
   group's only member and have that mean something.

Rootless Docker was considered and rejected for this wave: it changes the socket path, the
`docker.service` dependency both units carry, and the uid mapping the `chgrp 10000` ownership
model depends on.

### 3.2 SSH hardening is validate-then-reload, never restart

Ubuntu 24.04 ships `Include /etc/ssh/sshd_config.d/*.conf` in the default `sshd_config` and
activates ssh by socket. The script writes one drop-in (`PasswordAuthentication no`,
`PermitRootLogin no`, `KbdInteractiveAuthentication no`, `PubkeyAuthentication yes`), runs
`sshd -t`, and **refuses to reload if validation fails**. A drop-in is naturally idempotent:
rewriting the same file is a no-op.

`reload` rather than `restart` so existing sessions survive the change — the operator's live
session is the recovery path while the new configuration is being proven.

### 3.3 Docker comes from the apt repository, not a piped installer

`curl … | sh` executes an unreviewed remote script as root. This project pins its base image
by digest and re-runs a security audit on every upgrade (`Dockerfile`, `SECURITY-AUDIT.md`);
a piped root installer in the provisioning path contradicts that posture for no gain. The
script installs the keyring, writes the apt source, and installs `docker-ce`, `docker-ce-cli`,
`containerd.io`, `docker-buildx-plugin`, `docker-compose-plugin`.

### 3.4 `--check` mode

`provision.sh --check` verifies every invariant the script establishes, changes nothing, and
exits non-zero on drift. It exists for three reasons: it is the runbook's verification step;
it proves idempotency without mutating a box twice; and it is the only artifact in this
deliverable that observes the *host* rather than a file's text (§7).

### 3.5 OS gate

The script refuses a host that is not Ubuntu 24.04 (`/etc/os-release`) unless `--force-os` is
passed. Drop-in `Include`, socket activation, and the apt source are all 24.04-specific; a
silent partial success on another release is worse than a refusal.

## 4. `deploy/provision.test.py`

Follows `deploy/units.test.py` in shape, placement and honesty, and is registered as its own
CI step — `run-bin-tests.sh` discovers `bin/*.test.py` only, so `deploy/` is invisible to it
(`units.test.py` carries the same note, and `.github/workflows/ci.yml:108` is the precedent).

Assertions: the reserved names appear in the guard; no `-aG docker`; no pipe-to-shell anywhere;
no `ufw --force reset`; no truncating redirect onto `authorized_keys`; `sshd -t` appears before
any reload, asserted by line index rather than substring presence; `set -euo pipefail` present;
and `bash -n` for real syntax.

**What this suite does not prove, stated because a green suite otherwise implies it:** these
are text assertions about a shell script. They prove the script *says* the right thing. They
do not prove a box ends up hardened, that `ufw` is active, that `sshd` rejects passwords, or
that Docker installed. Only `--check` against a real host observes any of that.

Six tests in this project have passed for reasons unrelated to their claims, and reading found
none of them. Each assertion here is therefore written to be proven by making it fail against a
deliberately broken copy of the script before it is trusted — in particular the `sshd -t`
ordering assertion, which a substring check would satisfy no matter where the validation
appeared.

## 5. `deploy/BRING-UP.md`

Placed beside `provision.sh` and the units rather than under `docs/`: it is living operational
documentation re-run per box, not a dated artifact, and `README.md:957` links to it.

0. **Provision the box.** Hostinger KVM 2 (2 vCPU / 8 GB / 100 GB NVMe), Ubuntu 24.04 LTS,
   plain OS template. Generate the keypair locally.
1. **Harden.** Run `provision.sh` as root, verify with `--check`. **Lockout protocol:** keep
   the original root session open, prove key-only login in a second session, close the first
   only then. Includes recovery via Hostinger's browser console, because SSH hardening is the
   ordinary way a fresh VPS is bricked. Also verifies gid 10000 is free or already named
   `hermes` (§2.1), and that `docker` has no members yet.
2. **Lay out the box** per the §2.2 table.
3. **`.env`.** `HERMES_GOVERNANCE_DIR=/var/lib/hermes/governance`. Dummy credentials.
   Never `docker compose config` — it renders `env_file` secrets in cleartext.
4. **Build and start.** `sudo docker compose up -d --build`, then the README "First run"
   smoke checks.
5. **Measure the bind paths (§2.3)** before enabling any unit. The proxy is not running yet,
   so its log is not the instrument here: create the mutation-tier container without starting
   it and read back what Docker actually received —

   ```
   sudo docker compose --profile tools create ads-mutator
   sudo docker inspect <container> --format '{{json .HostConfig.Binds}}'
   sudo docker rm <container>
   ```

   `HostConfig.Binds` is the same string set the proxy compares against `--allow-bind` when
   `DOCKER_HOST` points at it, so this is the faithful measurement and it touches no
   credential and starts nothing. **Not `docker compose config`**, which renders `env_file`
   secrets in cleartext. On mismatch: stop, record the finding, do not widen the list.
6. **Hand off** to `README.md:957` steps 1–5, then to the 2026-09-17 handoff §2–§5.

## 6. `.env.example` correction

`HERMES_GOVERNANCE_DIR` becomes `/var/lib/hermes/governance` with a comment naming the units
as the reason it is not free-choice. Two lines, in a file this work already depends on, closing
the foot-gun §2.2 describes.

## 7. What is proven how — stated, not assumed

| Claim | Proven by | Status |
|---|---|---|
| The pinned base image resolves on amd64 | Registry query, 2026-09-18: `sha256:f7b3505…` is an OCI image index carrying `linux/amd64` and `linux/arm64` | MEASURED |
| Disk budget | Same query: amd64 variant is 33 layers, 0.95 GB compressed | MEASURED |
| The units hardcode the §2.2 layout | Direct read of both unit files | MEASURED |
| The script says the right thing | `provision.test.py` | Automated, text-level only |
| The box *is* hardened | `provision.sh --check` on the host | UNPROVEN until phase 1 runs |
| `adduser hermes` collides with gid 10000 | Reasoning from `adduser` behaviour + the step-1 guard text | INFERENCE — measured in phase 1 |
| Compose bind sources match the allow-list | Nothing yet | UNPROVEN — phase 5 measures it |

## 8. Scope boundaries

**In:** `provision.sh`, `provision.test.py`, its CI step, `BRING-UP.md`, the `.env.example`
line.

**Out:** the systemd units, `docker-create-proxy.py`, the allow-list, `units.test.py`,
`README.md:957`'s sequence, and every item in the 2026-09-17 handoff's §2–§5. Also out: the
§2.3 resolution, the handoff's §6 gate items (F3 hardening, `UMask=0077`, audit-log
truncation), and any credential provisioning.

## 9. Constraints carried

- **The VPS is a deploy target, not the dev workshop** (canon, 2026-07-17). These artifacts are
  written and tested on the laptop, landed via PR, and only then run on the box.
- **Mutation stays disabled.** No kill switch is created by any artifact here.
- No client names, customer ids, campaign ids, metrics or drafts in any artifact. No credential
  value or sha12 in a tracked file. The runbook uses placeholders throughout.
- `main` is protected — land via PR, and check CI on the merge commit, not only the PR.
- Stage by explicit path only. The operator's 5 tracked and 46 untracked working-tree entries
  are not part of this work.

## 10. Evidence

- Tree at `e1c411b`; `origin/main` identical (0/0); index empty. Measured 2026-09-18.
- CI green on the merge commit `e1c411b`. `10c7ed2` red as the handoff documents.
- Suites at `e1c411b`, all on darwin: bin 27/27, node 22/22, `deploy/units.test.py` 11/11,
  `docker-create-proxy.test.py` 40/40. Platform-gated assertions pass vacuously off Linux.
- This machine is `arm64` and has no `~/.ssh`, no Docker daemon, and no VPS access.
- `infra/hermes-agent/deploy/` contains three files: the two units and `units.test.py`. No
  provisioning or deploy script exists anywhere in the repo.
