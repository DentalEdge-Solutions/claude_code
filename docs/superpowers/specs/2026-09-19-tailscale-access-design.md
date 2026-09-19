# Tailscale access to the Hermes dashboard: design note

> **Status: PROPOSAL. Not approved, not scheduled, nothing built.**
> Written 2026-09-19 against the tree at `5807db8`, after evaluating an external
> VPS deployment guide (Divisual / Juan Pe Navarro, "Connect the Hermes Agent
> Desktop App to Your VPS") as reference material.
>
> This document exists because a network-boundary change is the category canon says
> to decide deliberately. It is the input to a future brainstorm/plan, not a
> substitute for one. Adoption goes through the project's normal gates.

## 1. What is proposed

Use **Tailscale as the network path** from the operator's machine to the Hermes
dashboard running on the VPS, replacing the current SSH-tunnel-only access.

## 2. Why this is not a new architectural decision

Canon already contemplated it. `canon/2026-07-21-adopt-nous-hermes-agent-runtime.md:46`:

> "Local-first → hardened VPS (bind loopback + SSH/Tailscale tunnel; auth required
> for any public bind)."

And `infra/hermes-agent/SECURITY-AUDIT.md` says it twice:

> `:40` — "**No** `network_mode: host`; explicit `127.0.0.1:PORT` + SSH/Tailscale
> tunnel (no public bind)."
> `:45` — "Dashboard: require an auth provider before any non-loopback bind (fails
> closed since June 2026); put behind VPN/Tailscale."

So the question is not *whether* Tailscale, but *how*, and the audit already fixes
the shape: behind the VPN **and** authenticated, never one instead of the other.

## 3. The adaptation that matters

The source guide uses Tailscale as a **substitute** for authentication. Its step 5
runs `hermes dashboard --host $TSIP --port 9119 --insecure`, binding the dashboard
to the Tailscale interface with auth disabled, on the reasoning that the tailnet is
private.

**We reject that specific shape**, on our own recorded evidence.
`SECURITY-AUDIT.md:42-43` notes that an unauthenticated public dashboard/API was the
entry point for the June 2026 attack that planted an SSH-key backdoor. A network
boundary is not an authentication boundary: anything that joins the tailnet — a
compromised laptop, a stale device key, a mis-scoped ACL — reaches an `--insecure`
dashboard with no second gate.

Tailscale is therefore an **additional** layer, not a replacement one.

## 4. Proposed shape

1. The compose port-map stays exactly as it is: `127.0.0.1:9119:9119`. No bind to
   the Tailscale interface, no public bind.
2. `HERMES_DASHBOARD_BASIC_AUTH_USERNAME` / `_PASSWORD` stay **mandatory**. The
   dashboard is never started with auth disabled.
3. Tailscale proxies the loopback service onto the tailnet — `tailscale serve`
   appears to be the right mechanism, but see §6: this is unverified.
4. Tailnet ACLs restrict which devices may reach the node, so device scope is
   explicit rather than "anything signed into the account".

Net effect: two independent gates (tailnet membership, then dashboard auth) where
today there is one (SSH key), and where the guide would leave one (tailnet only).

## 5. What this does NOT change

- The Docker architecture. No `network_mode: host`, no socket mount, no new bind.
- The governance store, the kill switch, the audit log, the approval gates.
- The `hermes-docker-proxy` / `hermes-broker` units and their hardening.
- Project delivery. Onboarding a project remains a PR touching
  `registry/projects.yaml`, `docker-compose.yml` and possibly the proxy's
  `--allow-bind` list — not a `git clone` on the box.
- `provision.sh`. Tailscale is a separate, optional bring-up phase; the hardening
  script keeps its single purpose and its `ufw` default-deny posture. A Tailscale
  interface does not require opening an inbound port in `ufw`.

## 6. What must be MEASURED before this is built

Stated as open questions rather than assumptions, because this branch has already
paid for one unsourced assumption about a third party's behaviour (`ufw status`
rendering `ALLOW` vs `ALLOW IN`, which made a security check a silent no-op).

| Question | Why it blocks | Status |
|---|---|---|
| Does the Hermes Desktop app accept **basic auth**, or does it require a bearer `HERMES_DASHBOARD_SESSION_TOKEN`? | If it cannot do basic auth, §4.2 and the app are incompatible and the choice is a token-based auth provider — **not** `--insecure`. | UNVERIFIED |
| Does `tailscale serve` proxy a loopback port to the tailnet with the semantics assumed in §4.3? | The whole shape depends on it. | UNVERIFIED |
| Does `check_firewall` report drift when Tailscale is present? | `provision.sh` treats any inbound rule beyond SSH as drift. Tailscale may add interface state that reads as drift, producing a false alarm on every `--check`. | UNVERIFIED |
| Does the `ufw` default-deny posture interfere with tailnet traffic? | If it does, the remedy must not be widening the inbound allow-list. | UNVERIFIED |

**None of these may be resolved by reasoning.** Each needs an observation on a real
host, and the third is the one most likely to bite: a security check that cries wolf
on every run gets ignored, which is its own failure.

## 7. Scope boundaries

**In, if approved:** a Tailscale bring-up phase in `deploy/BRING-UP.md`; tailnet ACL
guidance; the Desktop connection procedure once §6 is answered.

**Out:** any change to `provision.sh`'s purpose; any dashboard auth relaxation; any
change to project delivery or the governance tier; Tailscale as a transport for the
mutation rail (the broker reaches Docker through the proxy over a unix socket and has
no business on a network).

## 8. Constraints carried

- The VPS is a deploy target, not the dev workshop (canon, 2026-07-17). Any tooling
  is written and reviewed locally, landed via PR, then run on the box.
- `main` is protected — land via PR, and check CI on the merge commit.
- External sources are raw-source authority until they pass the project's gates. This
  note is an evaluation of reference material, not an adoption.
- No credential value or token in any tracked file.

## 9. Evidence

- Guide read as reference material at
  `/Users/ericksicard/RECURSOS YOUTUBE/HERMES AGENT + CLAUDE CODE/Hermes-Agent-VPS-Claude-Code-Master-Prompt-English.md`,
  337 lines, 2026-09-19. Not executed.
- Canon sanction: `canon/2026-07-21-adopt-nous-hermes-agent-runtime.md:46`.
- Audit sanction and the auth requirement: `SECURITY-AUDIT.md:40,42-43,45`.
- Current exposure measured: `docker-compose.yml:72` binds `127.0.0.1:9119:9119`;
  `.env.example:21-30` keeps the dashboard off unless `HERMES_DASHBOARD` is set and
  documents that a non-loopback bind requires an auth provider.
- Tailscale appears nowhere in the tree today except those two references.
