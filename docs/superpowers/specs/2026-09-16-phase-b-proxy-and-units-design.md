# Phase B — socket proxy and systemd units: design

> **Written 2026-09-16.** Brainstormed from
> `docs/superpowers/specs/2026-09-16-phase-b-brief.md`, against the tree at `ab0e6f5`.
>
> **This document is an AMENDMENT to Tasks 10 and 11 of
> `docs/superpowers/plans/2026-08-24-hermes-governed-syscall.md`, not a replacement for
> them.** Those tasks already carry 288 and 254 lines of TDD-structured work that is mostly
> correct. Everything below is a delta against them, so there is one source of truth for the
> parts that did not change. Where this document and that plan disagree, this document wins;
> where it is silent, the plan stands.
>
> Every measurement is stated with what produced it. Per **R22**, everything measured under
> Docker Desktop says nothing about the VPS.

## 1. What the proxy actually protects — the framing that drives the design

**A compromised broker already holds the Ads write credential.** Measured:
`run-ads-mutate.sh` reads `.env.gaw` in its own process (`:74`) and the broker invokes it as
a subprocess (`hermes-broker.py:480`), so anything running as the broker's user can read the
credential directly. It does not need Docker, a container, or the proxy to reach the client's
account.

So the proxy is **not** what protects the client account from a compromised broker; that is
already lost at the moment of compromise. What the proxy protects is **the host**: on a VPS,
Docker socket access is root, and without the proxy a broker compromise becomes every other
client's data, every other project on the box, persistence, backups, and lateral movement.

Two things follow, and both shape the rest of this document:

1. **Host containment is the security property.** Statements like "a broker compromise yields
   the ability to start that one container" must be evaluated against *host* reach, not
   against rail integrity.
2. **The audit trail is the secondary property worth defending**, because it is the one thing
   the previous wave (S3-b) bought and the one thing a compromised broker could otherwise
   erase. A design that leaves the log directly writable by attacker-chosen code undoes that
   purchase one wave later.

## 2. The principle

> **Anything in the `POST /containers/create` body that can redirect trust to an
> attacker-writable path must be pinned.**

The executor has exactly **one** writable mount — `log/`. Every create-body field that could
point the executor at a file inside it is therefore a hole. This principle is sharper than an
enumeration of dangerous fields, and it is what the plan's current denylist misses.

## 3. Finding: the create-body policy pins the image and little else

Task 10's `decide()` pins `Image` and screens `HostConfig` against a denylist. Measured
against the code as written, the plan's own stated property — *"a broker compromise then
yields the ability to start that one container, not the ability to do anything on the host"*
— is not achieved:

| gap | what a compromised broker can still do |
|---|---|
| `Binds` is a **denylist**, exact-match on `("/", "/etc", "/root")` plus `endswith("docker.sock")` | mount `/etc/shadow`, `/home/<user>/.ssh`, `/proc`, or **the governance store read-write** — which hands the governed party the approvals directory and the kill switch |
| `Entrypoint` / `Cmd` unpinned | run arbitrary code **inside** the pinned image |
| `User` unpinned | run as root in-container, changing what every bind means |
| `Env` unpinned | repoint `HERMES_GOVERNANCE_ROOT` at a fake store built inside `log/` |

An allow-list is straightforward here because the legitimate call is nearly fixed:
`docker-compose.yml`'s `ads-mutator` declares
`entrypoint: ["python3", "/opt/cc-bin/apply-changeset.py"]` and seven binds — six `:ro`, one
read-write (`log/`) — and only the changeset arguments and the injected credential vary.

### 3.1 `Cmd` — the sharpest edge, and why it must be constrained

Pinning `Entrypoint` alone is **not sufficient**. The executor accepts `--projects`
(`apply-changeset.py:409`), and `--projects` selects the file that
`changeset_lib.read_mutate_execute` reads for `runner`, `script_dir`, `allow` and `caps`
(`changeset_lib.py:271-278`) — that is, **which program runs**.

So: write a YAML into the one writable mount, pass `--projects /opt/governance/log/<x>.yaml`,
and arbitrary code executes despite a pinned image *and* a pinned entrypoint.

The legitimate path never passes it. Measured: `hermes-broker.py:506` builds exactly

```python
argv = [MUTATE_SH, "--client", slug, "--changeset", cid, "--request", rid]
```

— three flags, and a test already pins that shape
(`hermes-broker.test.py:341`). So refusing `--projects` and `--registry` outright costs the
rail nothing.

## 4. The amended `decide()` policy

**Pinned exactly:**

- `Image` — unchanged from the plan.
- `Entrypoint` == `["python3", "/opt/cc-bin/apply-changeset.py"]`.
- `User` — **must be absent or empty.** Stated precisely because it is easy to get wrong: the
  Dockerfile sets `USER hermes` (`Dockerfile:38`) and compose does not override it, so the
  legitimate create carries **no `User` field at all**. The check is "must not be set", not
  "must equal 10000" — a check written the second way would refuse every legitimate call.

**`Cmd` — allow-list the three legitimate flags** (`--client`, `--changeset`, `--request`)
with shape-validated values, and **refuse `--projects` and `--registry`** outright (§3.1).

**`Binds` — allow-list, replacing the denylist.** Exactly the seven sources from
`docker-compose.yml`, **with the `ro`/`rw` flag as part of the match** — six read-only, only
`log/` writable. A bind that names a permitted source with the wrong flag is refused: `rw` on
a directory the design says is `ro` is the whole attack.

`${HERMES_GOVERNANCE_DIR}` is the only variable in those paths, so the proxy takes
`--governance-dir` alongside `--image` and constructs the expected set at startup.

**`Env` — pin `HERMES_GOVERNANCE_ROOT`.** The `GOOGLE_ADS_*` variables stay free: they carry
the credential and vary per run, and per §1 the credential is not what the proxy defends.

**Kept from the plan, unchanged:** the deny-by-default endpoint allow-list; `FORBIDDEN_HOSTCONFIG`
(including `Mounts`, which blocks the newer mount API from bypassing the `Binds` check); the
`host` `NetworkMode`/`PidMode`/`IpcMode` refusal; refusing a create with no `Content-Length`
(a chunked body cannot be inspected before forwarding); and the 1 MiB body cap.

## 5. Making the pins enforceable rather than aspirational

Every pinned value already exists in a reviewed, version-controlled file:

| pinned value | source of truth |
|---|---|
| `Entrypoint`, the seven binds and their flags | `infra/hermes-agent/docker-compose.yml` |
| the three permitted `Cmd` flags | `infra/hermes-agent/bin/hermes-broker.py:506` |

So the coupling is testable: **parse both and assert the proxy's constants match.** A mount
added to compose without updating the proxy fails in CI rather than breaking the rail on the
VPS.

This is a shape the project already uses — `install.sh`/`uninstall.sh` must mirror each other,
and S3-b required the pre-flight's `REMEDY` and the README to stay verbatim-identical. The
sync test is that rule applied to a third pair.

**The same test asserts `seen/` is absent from the bind allow-list.** `iter_seen_records`
(`changeset_lib.py:682`) still fails **open** on a missing file, which is safe *only* because
the executor cannot reach `seen/`. Phase B is the wave most likely to touch mounts, so the
assertion belongs here.

## 6. Deployment — three findings against Task 11

### 6.1 As planned, the broker cannot reach the proxy. The rail is dead on first boot.

**MEASURED** in `hermes-agent-claude:latest` with a live listener and a positive control:

| layout | broker connect |
|---|---|
| as planned — `RuntimeDirectory=hermes`, `RuntimeDirectoryMode=0750`, `User=hermes-docker-proxy` | **`[Errno 13] Permission denied`** |
| directory and socket group-owned by a group the broker belongs to (`0750` / `0660`) | **CONNECTED** |

`RuntimeDirectory=hermes` creates `/run/hermes` owned `hermes-docker-proxy:hermes-docker-proxy`
at `0750`; the broker is a different user and not in that group, so it cannot traverse the
directory. Task 10 compounds this by specifying the socket as "mode `0600` and owned by the
broker's user" — the proxy cannot chown to another user, being non-root with
`NoNewPrivileges=true`.

**Design:** a dedicated group — `hermes-rail` — containing both service users, with
`/run/hermes` at `0750` and the socket at `0660`, both group-owned by it.

**Deliberately NOT `Group=hermes-broker` on the proxy.** That would work, and it would also
give the proxy read access to `.env.gaw` — the write credential it has no business seeing.
A dedicated group carries no other rights, which is the point.

### 6.2 The broker will not boot until `--bootstrap-logs` has run, and it restart-loops

Task 11's broker unit runs the pre-flight as `ExecStartPre` (`:67`) — already planned, not a
gap. But S3-b changed what that gate refuses: a registered client with no pre-created log is
now a refusal. Combined with `Restart=on-failure` and `RestartSec=5`, an unbootstrapped store
does not fail once — it **retries every five seconds indefinitely**.

**Design:** the deploy sequence runs `migrate-governance.py --bootstrap-logs --apply` *before*
`systemctl enable`, and Task 11's ordering states this explicitly. A first boot into a
restart loop is a bad way to learn it.

### 6.3 The store's ownership relative to the broker is unspecified, and S3-b made it matter

Task 11 specifies `User=hermes-broker` / `Group=hermes-broker` and deliberately not the docker
group, but says nothing about the governance store's ownership. S3-b's new check does **real
I/O** (it reads `clients.json`) where every sibling check only *simulates* access for a
hypothetical uid.

**MEASURED** (store `root:10000` `0750`, one registered client with no log):

| broker identity | exit | `cannot stat` problems | names `--bootstrap-logs` |
|---|---|---|---|
| **not** in group `hermes`(10000) | 2 | **4** | only in the remedy text |
| in group `hermes`(10000) | 2 | 0 | yes — the real finding |

Both refuse, so the misconfiguration **fails safe** and cannot produce a vacuous pass. But only
one names the real problem; the other buries it under four spurious errors, which is the
diagnosis an operator acts on.

**Design:** the deploy sequence states that the broker user is a member of the executor's
group, and a test pins it.

## 7. What is proven how — stated, not assumed

The honest limit of this wave, written down rather than left to be inferred:

| proven by | what it covers |
|---|---|
| **unit test (CI, Linux)** | `decide()` exhaustively — every pinned field, every refusal, and a positive control for each: the legitimate create must be **accepted**. This is the bulk of the security property and it is genuinely testable. |
| **repo test** | the §5 sync assertions; unit *content* (broker not in the docker group, `ExecStartPre` names the pre-flight, `seen/` absent from the binds) |
| **container probe** (Docker Desktop — R22) | the §6.1 socket handoff; a real create passing and refusing through the proxy end to end |
| **UNPROVEN until the VPS** | systemd actually applying `ProtectSystem=strict` / `RestrictAddressFamilies` / `NoNewPrivileges`; the real endpoint set against Linux Docker; boot ordering under real systemd |

**No repo test can prove the last row.** Task 11's existing tests assert that unit *files say*
the right thing, not that the system behaves that way. That distinction must survive into the
PR body, because "the units are tested" would otherwise read as a guarantee this wave does not
make.

Per **R22**, Task 10 Step 1 must **re-measure the endpoint set on Linux** rather than inherit
D1's darwin table.

## 8. Scope boundaries

- **Not P6.** Measured: zero `DynamicUser` occurrences in the plan; both units use a static
  `User=`, and `vault-purge.py` is operator-run from a shell that has a passwd entry
  (`README:489`). P6 is a latent hazard, not Phase B scope, and its failure path already
  exports first and exits 3 with a loud warning naming the tarball.
- **Not truncation.** S3-b closed `unlink` on the audit log and left truncation open — `0660`
  grants write, and write includes truncate, at the same reversibility cost. **This design
  reduces it without closing it**: pinning `Entrypoint` means only `apply-changeset.py` runs,
  so truncation-by-arbitrary-code through this path is gone. A bug in the executor itself
  could still do it. Closing it properly needs append-only semantics (`chattr +a`) or a
  host-side writer — its own wave.
- **Not a VPS deploy.** Phase B is the precondition for one, not the act of one.

## 9. Constraints carried

- Python 3 **stdlib only** under `infra/hermes-agent/bin/`, the proxy included — it terminates
  one Unix socket and speaks HTTP to another, which is `socket` plus `http.client`.
- **Fail closed** — an unparseable body refuses; it is never forwarded.
- `--log-only` must be removed or made refuse-by-default before Task 11 installs the unit.
  *A proxy with a bypass flag is not a proxy.*
- **NEVER run `docker compose config`** — it renders `env_file` secrets in cleartext.
- No client names, customer ids, campaign ids, or credential values anywhere; invented slugs
  only.
- The kill switch is the **file** `~/.hermes/governance/control/mutation-enabled` and stays
  absent.
- `main` is protected — land via PR, **and check CI after pushing.** Local darwin runs fewer
  tests than the Linux runner: `applies()` gates real logic off and `main()` returns 0 before
  `check()` executes, so platform-gated tests pass vacuously off Linux. That cost ten days of
  a silently-red PR on S3-b.
- Container probe stores are built with in-container `mktemp -d` or a named volume, **never a
  bind mount** — Docker Desktop does not preserve `chown`'d ownership across one, so an unsafe
  layout can read as safe (design §6.4 footnote of the S3-b spec).

## 10. Evidence

- `docs/superpowers/plans/2026-08-24-hermes-governed-syscall.md` — **Task 10 at `:2740`,
  Task 11 at `:3027`**. This document amends both.
- `docs/superpowers/specs/2026-08-19-hermes-mutation-syscall-design.md` §6.4 — deviation D1
  and the measured 10-endpoint table.
- `docs/superpowers/specs/2026-09-16-phase-b-brief.md` — the brief this was brainstormed from.
- `docs/evaluations/2026-09-04-s3b-layout-probe.md` — the container-probe method and the R22
  disclaimer.
- The credential-governance canon entry (2026-08-17) — rule 2 (*a guardrail secures a path,
  never a capability; the measure of a safety model is its weakest reachable path*) is why
  this phase exists. Rule 1 (the isolation boundary is the **account**; a separate OAuth
  client id buys no revocation isolation) should be re-checked against whatever credential
  topology the VPS ends up with — that is a deploy-time question, not a Phase B one.
