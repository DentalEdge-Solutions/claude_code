# Upstream check — Nous Hermes Agent releases vs. the mutation-syscall work

> **Date:** 2026-08-24 · **Asked:** does the upstream "Quicksilver" release already solve Task 1
> (governed syscall), or supersede Plan 1? · **Answer:** no, on every one of the four questions.
> **Method:** GitHub REST API (`gh api`) against `NousResearch/hermes-agent`, plus the running image
> itself. Every negative below is paired with a positive control; nothing here is recalled.

## 0 · Identifier verification (the pointer in the brief was partly wrong)

| Claim in the handoff | Measured | Verdict |
|---|---|---|
| repo `NousResearch/hermes-agent` resolves | `gh api repos/...` → `The agent that grows with you`, pushed 2026-08-24 | **confirmed** |
| a release tagged `v2026.8.19` exists | `releases/tags/v2026.8.19` → `Hermes Agent v0.20.5 (v2026.8.19)`, published 2026-08-21 | **confirmed** |
| it carries semver `v0.20.5` | same release name | **confirmed** (as a *name*, not a git tag — `releases/tags/v0.20.5` is 404; only the date tag exists) |
| it is **"Quicksilver"** | Quicksilver is **v0.19.0 / `v2026.7.20`**, published 2026-07-20 — five releases earlier | **FALSE** |
| it is a **major** release focused on speed / reliability / multi-agent fleet | v0.20.5's own body: *"Patch release. This tag rolls up the ~323 PRs merged since v0.20.4 … Full curated release notes for this window will ship with v0.21.0"* | **FALSE** |

The codename and the description belong to v0.19.0; the version numbers belong to v0.20.5. The
handoff's mid-flight "correction" from v0.19.0 → v0.20.5 moved the numbers **away** from the release
the codename and description actually describe. Both halves of the pointer were individually
plausible and jointly wrong — which is why the page, not the prompt, had to settle it.

## 0b · The decisive measurement: we already run Quicksilver

```
$ docker run --rm --entrypoint sh hermes-agent-claude:latest -c 'hermes --version'
Hermes Agent v0.19.0 (2026.7.20) · upstream 3ef6bbd2
```

Our pinned digest (`nousresearch/hermes-agent@sha256:f7b3505…dad04a`, `infra/hermes-agent/Dockerfile:12`)
**is** the Quicksilver release. So the question "does Quicksilver already solve this" is answerable
against the image Plan 1 was built and measured on: whatever Quicksilver added, we have had all along,
and it did not make the governed path reachable. The genuinely-newer window is v0.19.1 → v0.20.5.

## 1 · Does upstream provide a governed host-side privileged-operation invocation? **No.**

Searched the upstream tree (not just the changelog) for the mechanism:

| Query (`gh search code --repo NousResearch/hermes-agent`) | Hits |
|---|---|
| `host broker approval` | 0 |
| `request spool` | 0 |
| `privileged host operation` | 0 |
| **control:** `iron_proxy` | **5** (`agent/proxy_sources/iron_proxy.py`, `hermes_cli/proxy_cli.py`, docs, …) |

The control returns hits, so the zeroes are evidence of absence rather than a broken search. There is
no spool, no broker, and no host-side syscall concept upstream.

**The nearest thing, and why it is not a substitute.** v0.20.0 re-landed the **iron-proxy
credential-injection egress firewall** (PR #70848, merged 2026-07-24; a revert-of-revert of #30179 via
#58489). Its property: *real API keys never enter the Docker sandbox* — containers get per-provider
stand-in tokens under the standard env names, and a host-side MITM daemon swaps them for the real
credential at the network boundary. Disabled by default (`hermes egress setup` → `start`).

Measured against spec §5 — *every input the guards trust must be unwritable by Hermes; every output
they produce must be unreachable by Hermes*:

- **Credential out of the container: yes, and genuinely structural** for Hermes's own `execute_code`
  Docker sandbox. This is a real property, not a convenience.
- **Can the agent forge its own authorisation: it does not have to.** Iron-proxy governs *possession
  of the credential*, not *authorisation of an action*. A stand-in token is a standing, unlimited
  licence to make every call the real credential permits. There is no per-action approval, no
  byte-bound change-set, no kill switch, no daily cap, no audit log, no single-use consumption. It is
  the shape spec §4 explicitly rejected: the privileged operation stays directly callable by the
  agent, with the credential quietly supplied.
- **Wrong locus anyway.** It wires `tools/environments/docker.py` — the sandbox Hermes spawns for
  `execute_code` — not our gateway container and not the `ads-mutator` one-shot.

**Verdict: candidate, not a drop-in, and not a Task-1 replacement.** Worth a future scout → audit →
adapt → eval pass on its own merits (it could eventually help the still-open path #10b, where the
*read* credential transits the gateway container), but it does not remove one component from Plan 2.

Also in v0.20.0, adjacent but policy-level, all in-agent and all model- or human-judged rather than
structural: `hermes approvals suggest`, operator-customisable `approvals.smart_policy`, a
consecutive-denial circuit breaker, and **"Docker/podman daemon-redirect commands require approval"**.
Note that Quicksilver made **smart approvals the default — an LLM reviewer judges flagged commands**.
That is a *model in the approval path*, precisely what mutation-tier spec §3 / syscall spec §17.1
forbid for this rail. It is a reason to keep the mutation gate outside Hermes's approval system, not a
reason to adopt it.

## 2 · Does multi-agent fleet management change project registration or our tiers? **No.**

"Fleet" upstream means gateway multiplexing and delegation — profile-based inbound routing, one bot
token serving many isolated profiles, live subagent transcripts, a durable delegation ledger, kanban
wakes, `fleet --plan` verification in v0.20.5. None of it is a project registry.

`infra/hermes-agent/registry/projects.yaml` is **ours**, not upstream's (`read_execute` at :56,
`mutate_execute` at :88–93). Upstream has no concept of it and therefore cannot change it. The
`read_execute` / `mutate_execute` tiers are untouched.

## 3 · Does anything supersede Plan 1's masking or one-shot executors? **No.**

The container's identity contract is byte-for-byte the same at v0.20.5 as at our v0.19.0:
`useradd -u 10000 -m -d /opt/data hermes`, `HERMES_HOME=/opt/data`, `/opt/hermes` immutable,
`WORKDIR /opt/hermes`. So **F7 still holds upstream**: everything in the container runs as one uid in
a shared PID namespace, and `/proc/<pid>/environ` remains readable across processes. Nothing upstream
separates a credentialed process from Hermes inside one container — which is the entire reason Plan 1
moved the executor out. The upstream security work in this window is real but orthogonal (SSRF-safe
DNS-pinned fetches, redaction at compaction boundaries, tier-3 credential read scoping, Windows
subprocess hardening, CVE pin refreshes).

Secret-source work (Bitwarden / 1Password / `SecretSource`, `${env:VAR}` refs) changes how Hermes
loads *its own* keys. It does nothing about a credential file exposed through a **bind mount**, which
is what Plan 1's `mask_paths` closes. Spec §18's named failure applies unchanged: environment and
filesystem are different exposure surfaces.

## 4 · Breaking changes to gateway / terminal tool / compose topology? **None that touch us.**

- **Upstream `docker-compose.yml` is byte-identical** at `v2026.7.20` and `v2026.8.19` (76 lines
  each; `diff -q` on the same pair of Dockerfiles correctly reports a difference, so the comparison
  works). Our compose is our own file regardless.
- **No release in the window carries a "Breaking" or "Migration required" heading** (grepped across
  all eight bodies from v0.19.0 to v0.20.5). One deprecation only: `max_async_children`, which we do
  not set.
- **Upstream Dockerfile did change**, in two ways that matter only *if* we upgrade: the Node source
  stage moved **22 → 26** (our derived image installs the `claude` CLI via npm on top of it), and a
  pinned SQLite 3.53.4 shared library is now built from source to dodge the WAL-reset corruption bug
  in Debian 13's 3.46.1.
- The terminal tool gained recoverable truncation, cwd echo, and failure hints; `read_file`'s default
  limit went 500 → 2000 lines and the default iteration limit 90 → 500. Ergonomics, no interface break.

⚠️ Caveat on method: `gh api compare/v2026.7.20...v2026.8.19` reports **7,852 commits** but the API
caps the file list at 300, so that endpoint's file list is *not* an absence proof. The compose and
Dockerfile conclusions above come from fetching those files at both tags and diffing them directly.

## Conclusion

**Nothing upstream removes any component of Plan 2, and nothing upstream invalidates Plan 1.** The
spool, `hermes-syscall`, the broker, the socket proxy, and the governance store all remain ours to
build. Plan 2 is **not** re-scoped.

**Do not upgrade the gateway on the strength of this check.** Every Plan 1 guarantee was measured
against the v0.19.0 image; v0.20.5 is a 7,852-commit, ~1,250-file window with no curated notes (they
are deferred to v0.21.0). An upgrade re-opens all of them and needs its own verification pass, plus a
Node 22 → 26 rebuild of the derived image. Recommend revisiting at **v0.21.0**, when the curated notes
for this window actually ship.

**Open candidate for a later scout → audit → adapt → eval:** iron-proxy egress firewall, for the
still-open read-credential path #10b.
