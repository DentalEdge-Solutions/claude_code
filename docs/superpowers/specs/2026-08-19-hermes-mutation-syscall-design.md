# Hermes Mutation Syscall — Design Spec

> **Date:** 2026-08-19 · **Increment:** Task 1 (governed syscall reachable from inside the container)
> **Status:** design (awaiting plan) · **Method:** brainstorming → spec → writing-plans → SDD
> **Builds on:** `2026-08-12-hermes-mutation-tier-design.md` (the rail this adds a caller to)
> **Client-agnostic by rule:** committed to the org repo, so it contains **no client names, no account
> IDs, no campaign IDs, no metrics, no drafts**. Real identities live only in the gitignored client
> registry on the Hermes host.

---

## 1 · Problem & goal

The mutation tier shipped a carefully governed rail: per-action human approval bound to bytes by
sha256, a `validate_only` dry run, a typed one-entry allow-list, four caps, a kill switch, an exact
undo, and a separate write credential injected per invocation. Every guarantee was verified live.

**That rail is unreachable by Hermes.** `run-ads-mutate.sh` is host-side; Hermes runs inside the
container and cannot invoke host scripts. Meanwhile Hermes's own terminal tool executes arbitrary
shell *inside* the container, which is a path with no governance at all.

> **The safe path isn't reachable and the reachable path isn't safe.**

That is the blocking issue for Hermes being an operating system over projects rather than a control
plane for one.

**Goal.** One entry point, inside the container boundary, that Hermes can call to *request* a
mutation, where the governance is **structural rather than policy** — meaning the answer to "what
stops Hermes from doing X" is "no mechanism exists," not "a check would catch it."

**The hard question this spec must answer:** if Hermes can call it, what prevents Hermes calling it
without a human approval? See §5 and §7.

---

## 2 · Measured findings that define this increment

Every row below was probed on 2026-08-19 against the running container, each paired with a control
that had to refuse. Nothing here is inferred.

| # | Probe | Control used | Result |
|---|---|---|---|
| F1 | Is a live credential file readable in-container? | a non-existent `.env.NOSUCHFILE` in the same directory | **Readable**: `.env.gaw`, `.env.ga`, `.env` (Hermes's own), and the ads repo's `.env`. Control correctly unreadable. |
| F2 | Are those the *live* credentials or stale copies? | known host fingerprints (bare convention) | **Live.** The in-container `.env.gaw` and `.env.ga` refresh-token fingerprints are identical to the host's. Fingerprints are deliberately not reproduced here — a sha12 is not a credential value, but it is a durable identifier of a live credential and does not belong in a tracked file. |
| F3 | Is the write credential in the gateway environment? | `grep -c '^PATH='` as a positive control | **No.** `printenv \| grep -c '^GOOGLE_ADS'` → `0`; control → `1`. The per-invocation injection property holds. |
| F4 | Which mounts are writable from in-container? | three `:ro` mounts that had to refuse | **`/opt/data` writable**, including `vaults/_governance/`. `/projects/claude_code`, `/projects/claude_google_ads`, `/opt/registry` all correctly refused. |
| F5 | Is the Google Ads SDK usable in the gateway container? | — | **Yes.** `/opt/ads-venv/bin/python3 -c "import google.ads.googleads"` succeeds. |
| F6 | Can the container reach Google? | `no-such-host.invalid` | **Yes.** `googleads.googleapis.com:443` and `oauth2.googleapis.com:443` both connect; control fails with `gaierror`. |
| F7 | Is an injected credential visible to *other* processes in the container? | a marker value that was never set (must yield 0) | **Yes.** A marker injected via `exec -e` was read from `/proc/<pid>/environ` by a separate exec. All processes run as `hermes` (uid 10000) in a shared PID namespace. Control → 0. |

**F1 + F4 + F5 + F6 together are a complete ungoverned mutation path that exists today**: arbitrary
shell, a readable mutate-capable credential (measured `MUTATE_CAPABLE`, `manager_admin=true`), an
importable SDK, and network reach. No approval, no cap, no kill switch, no audit log, no undo.

**F7 corrects a documented claim.** The README states that the write credential "reaches ONLY this
exec'd process." That is true of *delivery* and false of *visibility*: `docker compose exec -e` places
the credential in one process's environment, but `/proc/<pid>/environ` is readable by any same-UID
process, and everything in the gateway container is `hermes` (uid 10000). So during any run of
`run-ads-mutate.sh`, `run-ads-report.sh`, `collect-audit-data.sh`, or `audit-credential-access.sh`,
Hermes can read the injected credential by polling `/proc`. It is a timing window rather than a
resting exposure — but Hermes is a persistent agent and can poll. **This leak is closed by the isolated
executor container (§6.5) independently of Task 3**, because the credential then never transits a
container Hermes has a shell in.

**F4 is the finding that reshapes this increment.** All mutation governance state lives inside the
single read-write mount:

| State | Path today | Consequence of F4 |
|---|---|---|
| Kill switch | `vaults/_governance/mutation-enabled` | Hermes can **enable mutation globally** with one `touch` |
| Client registry | `vaults/_registry/clients.json` | Hermes can flip a dormant client to `active` |
| Change-sets | `vaults/<slug>/changes/<id>.json` | Hermes can author what executes |
| Approval records | `vaults/<slug>/changes/<id>.approval.json` | Hermes can **author its own approval** |
| Audit log | `vaults/<slug>/changes/log.jsonl` | Hermes can erase the cap consumption the guards count |

The brief's framing was that the safe path is unreachable. The measurement shows the sharper problem:
**the governance state that path reads is fully writable by the thing being governed.** Adding a
syscall in front of that rail would be a lock on a door whose hinges are on the outside.

---

## 3 · Scope

**In scope**

- A read-only **governance store**, host-owned, holding kill switch, client registry, approval
  records, byte-exact approved change-set snapshots, and the audit log.
- Relocation of that state out of the read-write `data/` volume.
- An **isolated one-shot executor container** so `apply-changeset.py` no longer shares a security
  domain with Hermes.
- A **request spool** (the mailbox) and `hermes-syscall`, a deliberately dumb in-container client.
- A **host-side broker** that drains the spool automatically and invokes the existing rail.
- Single-use consumption of approvals.
- Moving `audit-credential-access.sh` onto the isolated service, since it injects the **write**
  credential into the gateway container today (F7).
- A README correction: the write credential's isolation property, stated precisely (§15).
- Live verification against the authorised dormant pilot client only.

**Out of scope (deferred, each requiring its own decision)**

- **Model-authored change-sets.** Mutation-tier spec §3 forbids a model in the mutation path "even in
  principle." Letting Hermes draft proposals is a change to that rule, not an implementation detail.
  §17.1.
- **Hermes-callable undo.** §17.2.
- Additional action types, a dashboard approval UI, remote approval transport (§16.3), multi-project
  request types beyond the one already registered.
- Any change to `run-ads-report.sh` or `bin/run-ads-report.py` — **frozen** (Increment 3).

---

## 4 · Decisions taken in brainstorming

| Decision | Choice | Rationale |
|---|---|---|
| Execution locus | **Hermes requests; a host-side broker executes** | The write credential must never enter the agent environment. Anything Hermes can execute in-container needs the credential in-container. Requesting is the only shape that keeps the credential host-side by construction. |
| Rejected alternative | In-container execution with cryptographically signed approvals | Solves forgery elegantly, but forces the credential into the container permanently and collapses the privilege ladder. Also needs key management that the chosen shape does not. |
| Rejected alternative | Manual operator drain | Two human gates, only one of which reviews anything. Adds latency and the habit of pressing go without reading. Also leaves the reachability gap open. |
| Broker form | **Host process (systemd unit on the VPS), not a sidecar container** | A container driving `docker compose` needs the Docker socket, which is equivalent to host root — strictly worse than the problem being fixed. |
| Mailbox form | **Filesystem spool, not a local HTTP endpoint** | No port to expose, nothing to firewall, nothing to accidentally bind to `0.0.0.0` on an internet-facing host. |
| Executor locus | **One-shot isolated container**, not the gateway container | Same container = same security domain. No file permission arrangement separates Hermes from a process running beside it — and F7 shows this concretely: same UID plus a shared PID namespace makes an injected credential readable via `/proc`. |
| Approval integrity | **Byte-exact snapshot into a read-only store**, not hash-compare against a writable copy | Closes the draft→review→swap race, and makes "Hermes cannot influence what executes" true with no mechanism rather than with a check. |
| Approval reuse | **Single-use, consumed by the broker** | The rail was built for a human typing a command. A machine caller can repeat it; the caps alone bound that too loosely. |
| Drain | **Automatic** | The approval gate is the gate that reviews. Operator decision, 2026-08-19. |
| Syscall surface | `apply` only | Undo bypasses kill switch and caps and requires no approval. §17.2. |

---

## 5 · The trust principle

> **Every input the guards trust must be unwritable by Hermes. Every output the guards produce must be
> unreachable by Hermes.**

This is stronger than the brief's "Hermes supplies only an identifier, never the content," and it
subsumes it. It is also the concrete form of canon rule 2 — *a guardrail secures a path, never a
capability* — applied to state rather than to code paths.

The principle immediately forces the executor out of the gateway container. `apply-changeset.py` must
write the audit log and read the approvals; Hermes must be able to do neither. Two processes in one
container cannot have that relationship.

---

## 6 · Components

### 6.1 Governance store (host, outside the repo, outside `data/`)

Default `${HERMES_GOVERNANCE_DIR:-$HOME/.hermes/governance}`. It must be outside the repo, because the
repo is bind-mounted at `/projects/claude_code`, and outside `data/`, because that is the read-write
mount.

```
governance/
  control/mutation-enabled          # kill switch (absent = disabled = safe default)
  registry/clients.json             # client registry (moved from vaults/_registry/)
  approvals/<slug>/<id>.approval.json
  approvals/<slug>/<id>.changeset.json   # BYTE-EXACT snapshot of what was approved
  log/<slug>.jsonl                  # audit log (moved from vaults/<slug>/changes/)
```

**Not mounted into the gateway container at all.** Hermes can neither read nor write any of it.

Ownership on the VPS: the broker's dedicated system user, mode `700`; `.env.gaw` likewise `600` owned
by that user, so even the deploy user's shell cannot read the write credential.

### 6.2 Request spool (`data/spool/`, read-write to Hermes)

The mailbox. `requests/<request_id>.json` written by Hermes; `results/<request_id>.json` written by the
broker. This is the only new surface Hermes can write, and its schema is closed (§8).

### 6.3 `hermes-syscall` (in-container, mounted read-only at `/opt/cc-bin/`)

A small stdlib-only client. It can do exactly two things: write a well-formed request, and read back a
result. It holds no credential, performs no network I/O, and contains no policy — its power is bounded
entirely by what the broker accepts. It is deliberately dumb, because anything it could decide would
be a decision a model could influence.

### 6.4 Broker (host, systemd unit, its own user)

Single-threaded, one advisory lock per client slug. Watches `data/spool/requests/`, validates the
request against the closed schema, then invokes `run-ads-mutate.sh` with the two identifiers. It never
passes request content through to anything else. On completion it writes the result and, on a
successful apply, marks the approval consumed.

The broker is privileged host code (it needs Docker access, which on a VPS is effectively host root).
It must be reviewed as such: small, no network listener, and a closed input schema.

### 6.5 Isolated executor container (`ads-mutator`, one-shot)

`run-ads-mutate.sh` keeps its exact current interface. One thing changes: instead of `exec`-ing into
the long-lived gateway container, it does `docker compose run --rm --no-deps ads-mutator`, a new
single-purpose service built from the same image.

| Mount | Mode | Why |
|---|---|---|
| `${GOV}/approvals` → `/opt/governance/approvals` | `ro` | apply reads; nothing in-container may write |
| `${GOV}/control` → `/opt/governance/control` | `ro` | kill switch |
| `${GOV}/registry` → `/opt/governance/registry` | `ro` | client resolution |
| `${GOV}/log` → `/opt/governance/log` | `rw` | the only writable governance path, and only here |
| ads project | `ro` | the mutator and its pinned venv |
| `./registry` → `/opt/registry` | `ro` | `projects.yaml` |
| `./bin` → `/opt/cc-bin` | `ro` | `apply-changeset.py` |

It does **not** mount `data/`. It exists for one apply and is then gone. The pinned venv, the
per-invocation credential injection, and all eleven guards are preserved unchanged — they simply run
where Hermes has no shell.

### 6.6 Where each command runs

| Command | Runs | Credential | Callable by Hermes |
|---|---|---|---|
| `propose-changeset.py` | host | none | **no** (operator-authored, §17.1) |
| `approve-changeset.py` | host | none | **no** — and structurally cannot be, §7 |
| `hermes-syscall apply` | container | none | **yes** — identifiers only |
| broker | host | reads `.env.gaw` | no |
| `run-ads-mutate.sh` | host | injects `.env.gaw` | no |
| `apply-changeset.py` | one-shot container | injected | no |
| `run-ads-mutate.sh --undo` | host | injects `.env.gaw` | **no**, §17.2 |

---

## 7 · The approval snapshot

Today `approve` records the sha256 of the change-set and `apply` re-reads that file from the writable
vault and re-hashes it. That is sound against tampering: any edit invalidates the approval.

It is **not** sound against a race. In a world where Hermes can write the vault, the sequence
*Hermes drafts → human reads → Hermes swaps the bytes → operator runs `approve`* would bind the
approval to bytes the human never saw.

**Fix:** `approve-changeset.py` copies the reviewed bytes into `governance/approvals/<slug>/` and
`apply` executes from **that** copy. The hash check stays as defence in depth. The window closes
completely, because the approved artefact now lives somewhere Hermes cannot write at any point in the
sequence.

This is also what makes the brief's requirement literally true: **a model can never author both the
change and its approval**, because in v1 it authors neither (§17.1), and even under a future relaxation
it could author only the draft, never the approved copy.

**Single-use.** After a successful apply the broker writes `consumed_at` into the approval record
host-side (it is `:ro` inside the container, so the executor cannot do this itself). `apply` refuses an
approval carrying `consumed_at`. Rationale: the rail's caps were sized for a human typing a command; a
machine caller can repeat a request, and "at most 5 applies per client per day" is a looser bound than
"this approval authorises one apply."

---

## 8 · Request schema (closed)

```json
{ "request_id": "<uuid4>", "op": "apply", "client": "<slug>", "changeset": "<id>" }
```

Broker validation, fail-closed, in order:

1. Filename matches `^[0-9a-f-]{36}\.json$`; reject anything else, including symlinks.
2. Parses as a JSON object with **exactly** these four keys — any extra key is a refusal, not an
   ignored field.
3. `op` is the literal `"apply"`. No other value is accepted in v1.
4. `client` matches `vault_lib.SLUG_RE`; `changeset` matches `C.CHANGESET_ID_RE`.
5. `request_id` matches the filename and has not been seen before (replay refusal).

Only after all five does the broker shell out, and it passes the two validated identifiers as
`--client` / `--changeset`. No request field is ever interpolated into a command string.

---

## 9 · Guards

All eleven guards from the mutation-tier spec §7 are preserved in order and unchanged in meaning.
What changes is only *where the state they read lives*:

| Guard | Change |
|---|---|
| 1 kill switch | reads `/opt/governance/control/`; safe default unchanged |
| 2 client resolves and is `active` | reads `/opt/governance/registry/clients.json` |
| 3 change-set loads and validates | reads the **approved snapshot**, not the vault copy (§7) |
| 4 identity match | unchanged |
| 5 approval hash + expiry | plus: refuse if `consumed_at` is present |
| 6 daily caps | counted from `/opt/governance/log/<slug>.jsonl` |
| 6b injected credential belongs to this client | unchanged |
| 7 allow-list resolution + disjointness | unchanged |
| 8 full credential set + `ROLE=write` | unchanged |
| 9 `validate_only` all-or-nothing | unchanged |
| 10 live apply, logged and fsynced per action | log path relocated |
| 11 exit semantics | unchanged (§12) |

---

## 10 · Path enumeration — everything that can reach the external system

Canon rule 2 requires this list, because a guardrail secures a path and never a capability.

**Host paths (unchanged by this increment)**

| # | Path | Credential | Governed by |
|---|---|---|---|
| 1 | `run-ads-report.sh` (**frozen**) | read-only | platform backstop — Google refuses mutates |
| 2 | `collect-audit-data.sh` | read-only | platform backstop |
| 3 | `run-audit-bundle.sh` | read-only | platform backstop |
| 4 | `run-ads-audit.sh`, `run-trend-audit.sh` | none directly | orchestrate 1–3 |
| 5 | `audit-credential-access.sh` | both | structurally non-mutating (`validate_only` hardcoded, no flag to disable) |
| 6 | `run-ads-mutate.sh` — operator, direct | write | the full eleven-guard rail |
| 7 | Any host shell that can read `.env.gaw` | write | **irreducible** — this is the trust root |

**In-container paths**

| # | Path | Status after this increment |
|---|---|---|
| 8 | Hermes terminal → reads `.env.gaw` from the repo mount → SDK → Google | **OPEN until Task 3.** Measured live (F1/F2/F5/F6). |
| 9 | Hermes terminal → writes governance state under `/opt/data` → subverts the rail | **CLOSED** by §6.1 relocation |
| 10 | Hermes terminal → ads repo's own four mutators | guarded by `injected_credentials.py`, which refuses without a full injected credential set — but collapses into #8 if Hermes can read `.env.gaw` |
| 10b | Hermes terminal → polls `/proc/<pid>/environ` during any credentialed host-script run → harvests the injected credential (F7) | **CLOSED for the write path** by §6.5: the write credential no longer transits a container Hermes has a shell in. **Still open for the read path** (`run-ads-report.sh`, `collect-audit-data.sh`) — lower severity, since that credential is measured `READ_ONLY` and Google refuses its mutates server-side, but it should be recorded and closed the same way in a later increment. `audit-credential-access.sh --all` injects the **write** credential into the gateway container and must be moved to the isolated service as part of this increment. |

**Path added by this increment**

| # | Path | Governed by |
|---|---|---|
| 11 | Hermes → `hermes-syscall` → spool → broker → `run-ads-mutate.sh` → isolated container → mutator → Google | closed request schema (§8), all eleven guards (§9), approved-snapshot execution (§7), single-use approval, caps, kill switch |

**Paths deliberately not created:** there is no route by which Hermes-authored bytes become an
executed action, and no route by which Hermes reaches the credential, the approvals, the kill switch,
or the audit log.

**Residual risk, stated plainly.** Anything that can write the spool can cause an *already-approved*
change-set to be applied. That is the intended power of the syscall. It is bounded by single-use
approvals, the 24-hour expiry, the daily caps, and the kill switch. It is not bounded by anything else,
and that is the deliberate trade.

---

## 11 · Preconditions

**P1 — Task 3 must land, or the syscall's central claim is false.** While path #8 is open, Hermes can
bypass the syscall entirely and mutate with no governance whatsoever. The syscall is then a locked
front door beside an open window. **This spec's security claim is conditional on P1**, and the
implementation plan must sequence Task 3 before the live verification gate (§13).

**P2 — governance relocation (§6.1) is in scope here** and must land with the syscall, not after it.

**P3 — the kill switch stays absent at rest.** Mutation is disabled unless a task demands otherwise,
and re-disabled immediately afterwards.

---

## 12 · Failure semantics

Exit codes of `apply-changeset.py` are unchanged and remain load-bearing: `0` success, `1` usage,
`2` pre-flight refusal (**guaranteed nothing was mutated**), `3` failure after at least one live
mutation landed.

The broker maps these into the result file without collapsing them. A result is written on **every**
outcome including refusal, so **file existence is the discriminator** between "the broker has not
processed this yet" and "the broker processed it and refused" — these are different events and
emptiness cannot separate them.

`hermes-syscall` surfaces the broker's classification verbatim and never re-interprets it. In
particular it must never render a refusal as an error that looks retryable, because a model that
retries a refusal is a model applying pressure to a guard.

---

## 13 · Verification gate (live, operator-run)

Against the **authorised dormant pilot client only**, resolved programmatically via
`vault_lib.resolve('<slug>')` — never hardcoded. `.env.ga` pins no customer id by design, so every read
passes `--customer` explicitly.

1. `./audit-credential-access.sh --all --customer <digits>` → exit 0 before and after.
2. **P1 verified by probe:** from inside the gateway container, every credential file unreadable, with
   a known-readable control file proving the probe works.
3. Governance store unreachable from the gateway container — with a control that *is* reachable.
3b. **F7 closed for the write path:** during a live apply, poll `/proc/*/environ` from the gateway
   container for the write credential's fingerprint and find nothing, with the F7 marker probe re-run
   as a positive control proving the polling technique still works. Compare by sha12 only; never print
   a credential value.
4. Kill switch absent → syscall request → refusal at guard 1, result file exists, exit 2.
5. Kill switch enabled → request naming an **unapproved** change-set → refusal at guard 5.
6. Forged approval written into the old vault location → **not honoured** (proves the executor reads
   the governance store, not the writable copy).
7. Kill switch created *from inside the container* at the old path → no effect.
8. Full happy path on the dormant client, then `run-ads-mutate.sh --undo` host-side, then confirm the
   account is byte-identical.
9. Re-request the same change-set → refused as consumed.
10. Kill switch removed. Confirm absent.

---

## 14 · Testing

Stdlib-only Python suites under `infra/hermes-agent/bin/`, discovered by `run-bin-tests.sh`.

- **Confirm the test count changed** — not merely that the suite reports OK. A stray mid-file
  `unittest.main()` has previously caused six new tests to never run while appearing to pass.
- Every negative test pairs with a positive control; a probe proves nothing until it has refused what
  it should refuse.
- Request schema: extra key, wrong `op`, bad slug, bad id, filename/`request_id` mismatch, replayed id,
  symlink — each refused.
- Approval: expired, consumed, hash-mismatched, missing snapshot — each refused.
- Broker: refuses to shell out until all five validations pass; asserts the subprocess is **never
  spawned** on refusal, mirroring the existing exit-2 test methodology.
- Path relocation: guards read the governance paths and *not* the vault paths.
- `node scripts/run-all-tests.js` for the node suites; `infra/hermes-agent/bin/run-bin-tests.sh` for
  these. Both must be green.

---

## 15 · Guarantees preserved (must hold at whole-branch review)

- Approval binds **bytes** — strengthened, not relaxed, by the snapshot.
- No model output can become a mutation, even in principle (§17.1 keeps this intact).
- The write credential never enters the gateway/agent environment — re-verified by probe (F3), and now
  also by the credential file being unreadable there (P1) and by the credential no longer transiting
  that container at all (F7/§6.5). **State this precisely in the README**: the old wording ("reaches
  only this exec'd process") was true of delivery and false of visibility, and the corrected claim is
  that the write credential never enters the container Hermes runs in.
- `run-ads-report.sh` and `bin/run-ads-report.py` untouched.
- Kill switch, caps, allow-list disjointness, credential-role check, and the exact undo all intact.
- `:ro` project mounts; Hermes never writes a project tree.
- This increment adds a **caller**; it does not replace the rail.

---

## 16 · VPS deployment

**16.1 The host-side surface is not new.** `.env.gaw` must live on the VPS host filesystem under the
current design, and `run-ads-mutate.sh` is already host-side. The broker automates a host component
that has to exist there regardless.

**16.2 A small, deliberate departure from "deploy = run the same containers."** The broker is a
systemd unit, not a compose service, for the Docker-socket reason in §4. It runs as its own user, with
`.env.gaw` and the governance store readable only by that user — an isolation the local machine cannot
practically provide, so the VPS posture is *stronger* than local, not weaker.

**16.3 Approval transport is an open item, not a blocker.** Today the operator approves on the machine
that executes. Remotely, either the operator connects to approve (simple; preserves the host-only
property with no cryptography — start here), or approvals are produced elsewhere and signed. The
syscall interface is identical either way, so this can be decided in a later increment without
redesigning anything.

**16.4 Staging must be exercisable without real credentials**, per the local-first-deploy canon. A
staging broker with a dummy `.env.gaw` fails closed at guard 8 (`ROLE=write` / full credential set),
proving the plumbing with no live account. This is an explicit acceptance test, not an assumption.

---

## 17 · Deliberately deferred

**17.1 Model-authored change-sets.** Mutation-tier spec §3 forbids a model in the mutation path "even
in principle," and this increment does not touch that. Hermes cannot author a change-set; it can only
request application of one an operator wrote and approved. Relaxing this — Hermes drafts, a human
approves the bytes — is defensible under the snapshot design of §7, and it is the obvious next
increment. It is a **spec change requiring an explicit recorded decision**, not an implementation
detail, and it must not arrive by accident.

**17.2 Hermes-callable undo.** Undo deliberately bypasses the kill switch and the daily caps so that
cleanup is never blocked by the switch that stopped the damage, and it requires no approval. A
Hermes-callable undo would therefore be an unapproved account change on demand. Undo stays
operator-only: the recovery path should not be reachable by the thing you might be recovering from.

**17.3 Generalising to project eleven.** The spool and the registry manifest are the seam. Project
eleven should declare the governed actions it offers rather than have Hermes learn its internals —
the direction the credential-locus decision candidate already recommends, and the same manifest idea
Task 3 points at. Not built here; not designed around either.

---

## 18 · Open question for the operator

`.env` (Hermes's own, holding the Anthropic and provider keys) is also readable in-container (F1). That
is arguably correct — the gateway needs those keys — but it means the repo mount exposes *every*
`.env.*` in `infra/hermes-agent/`, including `.env.pr`, the draft-PR bot credential. Task 3's masking
should cover the whole directory rather than the two Ads files specifically, and the write-up should
say which of those exposures were intended.
