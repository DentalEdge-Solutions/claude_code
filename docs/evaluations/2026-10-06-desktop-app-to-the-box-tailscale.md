# Evaluation — connecting the laptop's Hermes Desktop app to the box, and whether Tailscale is a sound way

> **Date:** 2026-10-06 · **Asked:** is Tailscale a viable, secure way to connect the laptop's Hermes app to
> the Hermes box? · **Answer:** yes as a second layer in front of the dashboard's own login, never instead of
> it; but it is not needed to try the connection, which can be measured first over the SSH tunnel the box
> already has. **Method:** official documentation read on 2026-10-06, and the repo's own records. Nothing was
> measured, and nothing in the repo's code or on the box was changed by this evaluation.

## 1 · Sources, authority and what each verified (accessed 2026-10-06)

| Source | Authority | Verified there |
|---|---|---|
| [Hermes docs: Hermes Desktop](https://hermes-agent.nousresearch.com/docs/user-guide/desktop) | primary | The desktop app can use a remote backend. It connects to a running `hermes serve` process on port **9119** (the `tui_gateway` JSON-RPC/WebSocket API), not to the API server. The backend is protected by username and password (`HERMES_DASHBOARD_BASIC_AUTH_USERNAME`, `_PASSWORD`, and `_SECRET`, a signing secret so sessions survive restarts) or by OAuth (Nous Portal). Against a remote backend the app offers chat, terminal, file browser, settings, credentials management and sessions. Warning: "never expose a password-protected backend directly to the open internet; put it behind a VPN". For Tailscale it says to bind to the machine's Tailscale address and use `http://<tailscale-ip>:9119`. The app's gateway list also accepts SSH hosts. |
| [Hermes docs: API server](https://hermes-agent.nousresearch.com/docs/user-guide/features/api-server) | primary | The API server (default `127.0.0.1:8642`, bearer `API_SERVER_KEY`) is the OpenAI-compatible endpoint for other front-ends (Open WebUI and similar) and for another gateway's proxy mode. It gives "full access to hermes-agent's toolset, including terminal commands". The desktop page does not involve it. |
| [Tailscale docs: Serve](https://tailscale.com/kb/1312/serve) | primary | Serve routes traffic from other devices on the tailnet to a local service, can proxy to a `127.0.0.1` port, stays inside the tailnet (Funnel is the public variant), needs the tailnet's HTTPS certificates enabled, and adds identity headers. |
| [Tailscale docs: ACLs](https://tailscale.com/kb/1018/acls) | primary | With no policy written, the tailnet's default is **allow all**. A policy can limit a source (a user or device) to one port on one tagged device. Rules are deny-by-default once written and enforced on each device. |
| `infra/hermes-agent/docker-compose.yml:61-62` | repo | The box publishes the dashboard as `127.0.0.1:9119:9119`: host loopback only. |
| `infra/hermes-agent/deploy/BRING-UP.md`, Phase 7 | repo | The dashboard is on, with mandatory basic auth, reached from the laptop through an SSH local forward to port 19119. "The Hermes Desktop app is out of scope. Whether it can authenticate against this gated dashboard has not been measured." |
| `.project-brain/decisions/candidates/2026-09-19-tailscale-is-the-one-adoption-…md` | repo (candidate, not canon) | Tailscale was already judged the one adoption from an external guide, as an ADDITIONAL layer beside mandatory dashboard auth; the guide's `--insecure` shape was rejected, because an unauthenticated dashboard was the entry point of the June 2026 attack recorded in SECURITY-AUDIT. Never implemented. |
| `docs/security-reviews/2026-10-06-review-7.md`, D1.1 and D4.1 | repo | Host listeners today: SSH on 22, the dashboard on `127.0.0.1:9119`, the local DNS stubs. Gateway container listeners: `[9119]`. Port 8642 does not listen. |

Not verified: whether Tailscale needs any inbound port on the host firewall (the ACL page does not say); whether
the box's image runs the same backend under its dashboard service that the desktop page calls `hermes serve`;
whether the desktop app accepts the box's basic auth through a forwarded port.

## 2 · Findings

1. **The desktop app uses the dashboard port, not the API server.** The remote backend is port 9119, which
   the box already runs behind a password. Port 8642 stays off and is not part of this.
2. **The connection may already be possible with no change to the box.** The SSH tunnel of Phase 7 presents
   the box's dashboard at `http://127.0.0.1:19119` on the laptop. Pointing the desktop app's remote gateway at
   that address is the cheapest test, and it changes nothing a review looks at. It has not been measured.
3. **What the desktop app would be able to do is what the dashboard password already allows:** drive the
   gateway's agent, its terminal inside the container, its files, settings and stored credentials. The gateway
   container holds the OpenRouter key and the dashboard password, and no Google or Anthropic credential
   (D4.1). So this is not a new kind of access, but it makes that access more convenient, which raises the
   value of the password and of whatever network path leads to the port.
4. **Tailscale is viable and can be made secure, as a second layer.** The sound shape for this box:
   - keep the compose bind on host loopback (no change to a fingerprinted file) and let `tailscale serve`
     proxy the tailnet's HTTPS to `127.0.0.1:9119`, instead of binding the dashboard to the Tailscale address;
   - keep the dashboard's own login on; never use `--insecure`; never use Funnel;
   - write an access policy, because the default is allow-all: one user's laptop, one tagged device, one port;
   - leave Tailscale SSH off, so the reviewed SSH posture does not change;
   - protect the Tailscale account with strong sign-in and device approval: whoever controls the account
     controls who is on the network.
5. **What Tailscale adds is convenience and device-level control, not a fix for a weakness.** The SSH tunnel is
   already encrypted and key-authenticated. Tailscale removes the need to keep a tunnel open and lets other
   devices (a phone) reach the dashboard, at the cost of a new root daemon on the box, a new vendor in the trust
   chain, and a security review: D1.1's expected listeners, `provision.sh --check` and the runbook would change.

## 3 · Recommendation

1. Measure first: connect the desktop app through the existing SSH tunnel. If it does not work, find out why
   before adding anything.
2. If always-on access is wanted, add Tailscale in the shape of finding 4, in the same box change as the
   periodic listener check (F50), so one security review covers both.
3. Record the decision in the project brain when it is made; the 2026-09-19 candidate is still unpromoted.
