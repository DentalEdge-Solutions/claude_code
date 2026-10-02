# Handoff 2026-10-02: Option B is live on the box; security review #6 PASS

**Start here in the next session.** Read this file, then `.project-brain/BRAIN.md`. Client names are written as
`<client>`; no customer ids or fingerprints appear here. This supersedes
`2026-10-01-option-b-part-3-merged-next-box-rollout.md`.

## Where things stand

- **On the box:** Option B (chat-triggered Google Ads audits) is applied and working. The box checkout is
  `6c4d08c`. A chat audit answers `ok` in the chat itself.
- **Review #6:** PASS 34/34 against checklist **v1.14**, signed off 2026-10-02. Report:
  `docs/security-reviews/2026-10-02-review-6.md`. The PASS is bound to the box as it is: a change under `bin/` or
  `deploy/` on the box, or to its credentials, re-opens it.
- **Brain:** canon `canon/2026-10-02-option-b-live-on-the-box-security-review-6-pass-34-34-checkl.md`.
- **Local only (gitignored `infra/hermes-agent/security-reviews/`):** both bundles and two OpenRouter console
  screens in `review-6/`, and the operator evidence file `2026-10-02-operator-evidence-review6.md`.

## What the rollout found (all fixed, merged and re-proven on the box)

| PR | Defect | Found by |
|---|---|---|
| #90 | A stray entry in `jobs/` restarted the root runner in a loop | parked follow-up, built before the rollout |
| #92 | The app MCP server did not answer Hermes's liveness ping while a call waited, so every chat audit's reply was lost ("MCP call timed out" while the audit finished `ok`) | the first chat audit |
| #92 | D10.6 compared the MCP config line for line; the gateway rewrites `data/config.yaml` (layout, plus keys of its own) | a trial evidence collection |
| #93 | D4.2's proxy hash changes after `systemctl daemon-reload` with the proxy untouched | the same trial |

Also from the rollout, now in BRING-UP: part 1 step 5 prints `STILL-PRESENT` when all parts are pulled at once
(the retired sidecar no longer clears the generated key file; check its date, then shred it).

## Worth repeating

- **Run a trial evidence collection before the real one** (a throwaway 64-hex key, output piped to a summary,
  nothing saved). It found two checklist rules that failed a healthy box.
- **An integration is not proven until it has run against the real counterpart.** The MCP server passed every
  test against stand-in clients and failed on the first real Hermes call.
- **Hermes facts measured on the box:** its MCP client pings each server every 180 s by default, allows 30 s, and
  reconnects on silence; it rewrites `data/config.yaml` during a chat session; `hermes mcp list` works without a
  TTY; the image bakes in no `ANTHROPIC_*`, `OPENROUTER_*` or `GOOGLE_ADS_*` env name.
- **Chat quota:** one run per client per UTC day. A manual `sudo run-client-audit <client>` does not count
  against it.
- **For the next review (#7):** the D4.2 baseline is `execstart_argv_sha256`
  `f5bde68c86420eb5580764b445b51f504b2d6afb48c31d651f408fe26dfa1c16` (restart- and reload-stable). Restate the
  nine standing D9.1 findings with reasons in the evidence file (the reviewer does not get earlier reports), and
  attach the OpenRouter console screens, uncropped.

## Open follow-ups

**From the review #6 sign-off:**
1. Add the 16 findings opened since review #5 to the findings doc
   (`docs/superpowers/specs/2026-09-21-vps-first-bring-up-findings.md`).
2. Add the dashboard basic-auth password to the D2.1 credential inventory and the leak checks.
3. The retired ADMIN write token is still valid at Google (accepted risk under D3.2). Revoke it when the shared
   grant can be separated.

**Deferred code items** (each fails closed; all accepted under D9.1 in review #6). Any change under `bin/` or
`deploy/` changes the box fingerprint and re-opens the review, so batch them:
4. The env probe cannot detect a mounted real credential file (a `test -e /etc/hermes` line would).
5. A probe killed by the collector's 600 s timeout skips its cleanup.
6. `probe_egress` ignores its return codes; `_sudo_rules` reads clean when `sudo` did not run; `d10_3` loses the
   whole item when the app user is missing; `load_env_value` does not strip an inline `# comment`.
7. D10.6's top-level rule refuses a top-level key holding an indentless list or a key name outside
   `[A-Za-z_][A-Za-z0-9_-]*`. A future Hermes config that has one fails with `top_level_not_plain` until the rule
   is widened deliberately.
8. The review's `--credentials-only` mode and "authorised credential set" cover Google values only.
9. BRING-UP part 2 step 7 uses `rm -f` where part 1 step 5 uses `shred -u`; the README's "one non-Google secret
   file" paragraph is stale.

**Rules that apply:**
- Any change to `CHECKLIST.md` needs a version bump above 1.14.
- No push without the operator's word.

## Next

Nothing is blocking. Candidates, in the operator's order of choice: the dashboard over Tailscale (spec §11: the
next chat surface, with its own review), the follow-ups above as one batched change, or onboarding the next
client (BRING-UP part 1 step 8).
