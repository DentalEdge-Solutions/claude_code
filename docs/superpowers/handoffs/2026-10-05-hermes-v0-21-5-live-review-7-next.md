# Handoff 2026-10-05: Hermes v0.21.5 on the box with the API server off; review #7 is next

**Start here in the next session.** Read this file, then `.project-brain/BRAIN.md`. Client names are written as
`<client>`. This file carries no customer id, hostname, fingerprint or credential value. It supersedes
`2026-10-02-option-b-live-review-6-pass.md`.

## Where things stand

- **`main` is at `3ced410`** (merge of PR #100). Merged since the last handoff:
  - #95 canon entry for Option B live / review #6;
  - #96 review #6 follow-ups, checklist v1.15;
  - #97 brain fixes, the Hermes v0.21.5 evaluation and the sources;
  - #98 lost brain sources restored, two entries promoted;
  - #99 re-pin to Hermes v0.21.5;
  - #100 API server kept off, checklist **v1.16**.
- **The box** is at checkout `10b2c40` (#99), one pull behind `main`.
  - The gateway runs the derived image on **Hermes v0.21.5**, uid 10000, `printenv` present, `ads_audit` with 3 tools.
  - The live `data/config.yaml` has `platforms.api_server.enabled: false` appended (2026-10-05).
  - Measured after a restart: the gateway's listening ports are `9119` (the dashboard is **on**) and Docker's embedded DNS on `127.0.0.11`; 8642 does not listen.
  - Review #6's PASS no longer holds: the box changed. Review #7 is owed.
- **Not yet run on v0.21.5:** the two probes, a chat audit, the trial collection, the real collection, review #7.

## What happened (why v1.16 exists)

1. #99 re-pinned the base image after a laptop evaluation (`docs/evaluations/2026-10-03-hermes-v0-21-5-upgrade-evaluation.md`).
2. On the box, `/opt/hermes-agent/data/.env` appeared: 26 KB, owner uid 10000, mode 0600.
   - v0.21.5's `stage2-hook.sh` seeds it from the bundled `.env.example` and appends a generated `API_SERVER_KEY`.
   - With a key present, the gateway starts its OpenAI-compatible API server on container loopback `127.0.0.1:8642`.
   - v0.19.0 never did this, because its image lacked the template. The laptop evaluation missed it, because the generated file was never inspected.
3. Fix (#100), the upstream-supported switch: `platforms.api_server.enabled: false` in `config.yaml` (`gateway/config_env.py`, `gateway/config_loader.py`). Measured: `[8642]` without the switch, `[]` with it.
   - D2.1 inventories the file as `hermes-home-env` (key `api-server-key`, owner 10000, mode 0600, `credential_shaped_names: []`).
   - D4.1 adds `listeners`: expected `[]`, or `[9119]` with the dashboard on. Docker's resolver is counted apart in `docker_dns_listeners`, which must be `1`.
   - `SECURITY-AUDIT.md` gained three upgrade-audit steps: diff `stage2-hook.sh`; list what the first start writes into `/opt/data` (names only); list the container's ports.

## Box steps still owed (in order)

Label every block VPS / LAPTOP / HERMES CHAT, one paste per block, no placeholders. Ask the operator to paste output without the shell prompt (it carries the hostname).

1. Pull `main` (`3ced410`), then restart the gateway. Check the restart actually finished: the status must show `Up`, not `Restarting`.
2. `sudo run-client-audit --probe-env` and `--probe-egress`: `rc=0`, `host_credential_files_visible: false` ×4, `proxy_rc` 0, `drafter_rc` 0.
3. One chat audit for one active client: D10.8 needs an `ok` from chat within 7 days. The last one was 2026-10-02, and quota is one per client per UTC day.
4. Trial collection with a throwaway key (`openssl rand -hex 32`), output piped to a summary that prints statuses and labels only. Reuse the summary script from the 2026-10-05 session and add:
   - D4.1 `listeners` and `docker_dns_listeners`;
   - the D2.1 `hermes-home-env` row.
   Expect every item `observed`, `listeners [9119]`, `docker_dns_listeners 1`, `secret_env` `matches-file` for both labels (the dashboard is on), and `credential_shaped_names []`.
5. Real collection. Pass the review #6 `execstart_sha256` as `--last-pass-execstart`: it is the first full 64-hex string in the local `infra/hermes-agent/security-reviews/2026-10-02-operator-evidence-review6.md`. Copy it with `grep -o -E '[0-9a-f]{64}' … | head -1 | pbcopy` and read it on the box with `read -r -p`, never typed into a block. Then the fp key from `~/.config/hermes-review/fp.key`. Copy the bundle to `security-reviews/review-7/` and shred it on the box.
6. Laptop bundle: the operator's review #6 command (dormant pilot id, ads repo at its pin).
7. Draft the operator evidence file for review #7. It must cover:
   - D2.1 dashboard statement (on);
   - Anthropic key statement;
   - D3.2;
   - D4.2 baseline;
   - D8.1, D8.2;
   - D9.1: the nine standing findings, plus F26–F43 with their statuses;
   - D10.5: both console screens, the privacy screen uncropped including the whole Data Training section;
   - D10.8: the chat audit;
   - what changed since review #6 (#96, #99, #100, v0.21.5, the config switch).
   Then launch a fresh reviewer per REVIEWER-BRIEF against checklist **v1.16**.

## Open items (not blocking review #7)

- **Zombie candidates (operator).** Eight untracked duplicates of promoted entries remain in `.project-brain/`. The brain guard blocks the agent from deleting them, so the operator removes them.
- **Lost sources.** The AI-OS charter and memory corrections D-1…D-5 had empty `sources` before git ever recorded them; they are not reconstructed.
- **Real candidates.** Twelve untracked candidates still await a weekly review: security reviews #1, #4 and #5, D3.2, Tailscale and others.
- **Collector residuals.** A zero-width character, internal whitespace or inner quotes around a key, or a padded password under 8 characters, can still pass the guard. These are values the gateway could not authenticate with.
- **Auxiliary models.** v0.21.5's auxiliary fallback can use a paid OpenRouter model. Check that the `data_collection: deny` routing applies (D10.5).
- **Dashboard password hash.** v0.21.5 accepts `HERMES_DASHBOARD_BASIC_AUTH_PASSWORD_HASH`, so the plaintext password in the gateway `.env` could be replaced. Dashboard work.
- **Retired ADMIN token.** Still valid at Google (accepted under D3.2).
- **Leftover branch.** `origin/proposal/2026-07-24_22-54-03` holds one commit not on `main`.

## Rules that apply

- No push and no PR without the operator's word; the operator merges.
- Build work: plan, implementer, independent review, then ask before pushing.
- Any change under `infra/hermes-agent/bin/` or `deploy/` changes the box fingerprint. Any change to `CHECKLIST.md` bumps the version above 1.16.
- Verify against primary sources before an important decision, and record them in `docs/evaluations/` (canon `2026-10-03-verify-sources-before-important-decisions`). Inspect what a new Hermes version writes and listens on before trusting it.
- Never put a client name, customer id, hostname, fingerprint or credential value in the repo, the brain or the conversation.
