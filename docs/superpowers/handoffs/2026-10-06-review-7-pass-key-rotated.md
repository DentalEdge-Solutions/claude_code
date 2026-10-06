# Handoff 2026-10-06: review #7 PASS on Hermes v0.21.5; the OpenRouter key was rotated

**Start here in the next session.** Read this file, then `.project-brain/BRAIN.md`. Client names are written as
`<client>`. This file carries no customer id, hostname, fingerprint or credential value. It supersedes
`2026-10-05-hermes-v0-21-5-live-review-7-next.md`.

## Where things stand

- **Security review #7: PASS, 34 of 34, checklist v1.16**, signed 2026-10-06. Report:
  `docs/security-reviews/2026-10-06-review-7.md` (merged with this handoff as PR #101).
- **The box is at checkout `3ced410`** (merge of PR #100). `main` is ahead of it by docs only (PR #101 and the
  follow-ups below), which the box fingerprint does not cover.
- **The box** runs the derived image on **Hermes v0.21.5**, uid 10000, `ads_audit` with 3 tools.
  - `platforms.api_server.enabled: false` is in the live `data/config.yaml`; the gateway's listening ports are
    `9119` (the dashboard is on) and Docker's embedded DNS; 8642 does not listen.
  - The gateway holds a **new OpenRouter key**, created 2026-10-06 for the box only ($10, monthly reset),
    typed once into the installer prompt and stored nowhere else. The previous key is deleted at OpenRouter.
  - `hermes-docker-proxy` was not restarted: its `execstart_sha256` is unchanged since review #6.
- **Local, git-ignored evidence** is in `infra/hermes-agent/security-reviews/`: the operator evidence file
  `2026-10-05-operator-evidence-review7.md` and `review-7/` (both final bundles, the replaced bundles under dated
  names, three console screens).

## What review #7 found (that review #6 did not)

1. **A Data Training toggle was on at OpenRouter.** "Allow free endpoints that train on request data" was on
   until 2026-10-06. Review #6's privacy screen was cut off above it, so review #6 passed D10.5 on a statement
   that was not fully true. It is off now. Zero Data Retention was on throughout, and the key's last 30 days show
   one paid model only; the time before that is not covered by evidence.
2. **The "dedicated" OpenRouter key was not dedicated.** It was created 2026-07-22 for the laptop build, and a
   laptop gateway container was still running with it. A search of the laptop found the copy in the laptop
   checkout's `infra/hermes-agent/.env`. The laptop container was removed, the laptop key line blanked, and the
   key rotated: new box-only key, gateway recreated, old key deleted.
3. **The checklist's date rule bit.** The laptop bundle must be from the sign-off day. Evidence corrected a day
   after collection means a new laptop bundle; a change to the box (the rotation) means a new box bundle.

How the verdict moved: 32 PASS and 2 CANNOT-VERIFY (laptop bundle a day old), then 33 and 1 (D10.5: the key was
not dedicated), then 34 of 34.

## Follow-ups (none blocks the PASS)

Done on 2026-10-06, after the PASS (branch `docs/review-7-follow-ups`; docs outside `bin/` and `deploy/`, so the
box fingerprint is unaffected):

- **Findings document.** F44 to F51 record the v0.21.5 API server, the collector residuals, the auxiliary
  models, the plaintext dashboard password, the Data Training toggle, the shared key and the laptop gateway, the
  API-server-off controls, and the key that never expires.
- **Review #6's report** carries a dated correction about the toggle and the key.
- **README** ("The OpenRouter key is the box's alone"): what dedicated means, the replacement steps, and the
  operator's decision to **replace the key every 12 months** (next due by 2027-10-06), or at once on a suspected
  leak or a copy found outside the box. The README also names the third secret file, `data/.env`.

Still to do, with the next change that re-opens the review (anything under `bin/` or `deploy/`, or a checklist
change, which bumps the version above 1.16):

- **BRING-UP.** Move the key-replacement steps from the README into the runbook as a named block, with the two
  checks this review used: search the laptop for a copy of the key, and capture the privacy screen whole.
- **Checklist.** Document or drop `D7.1.records`; consider asking for the API-keys list as D10.5 evidence.
- **F50, the operator's open decision.** Whether the API-server-off controls, which sit in gateway-writable
  files and are measured only at review time, get a periodic listener check.
- The reviewer's process suggestion: give the reviewer the previous PASS report's header, or carry the baselines
  in the bundle.

Carried over from the previous handoff:

- **Laptop Hermes stack.** It is down, and its `.env` has an empty `OPENROUTER_API_KEY`. Before starting it
  again, create a separate laptop key. Never reuse the box's.
- **Zombie candidates (operator).** Eight untracked duplicates of promoted entries remain in `.project-brain/`.
  The brain guard blocks the agent from deleting them, so the operator removes them.
- **Real candidates.** Twelve untracked candidates still await a weekly review.
- **Lost sources.** The AI-OS charter and memory corrections D-1…D-5 had empty `sources` before git ever
  recorded them; they are not reconstructed.
- **Dashboard password hash.** v0.21.5 accepts `HERMES_DASHBOARD_BASIC_AUTH_PASSWORD_HASH`; the plaintext
  password in the gateway `.env` could be replaced. Dashboard work.
- **Retired ADMIN token.** Still valid at Google (accepted under D3.2).
- **Leftover branch.** `origin/proposal/2026-07-24_22-54-03` holds one commit not on `main`.

## For the next review (#8)

- `--last-pass-execstart` is review #7's `execstart_sha256`, which equals review #6's. It is the first full
  64-hex string in the local `infra/hermes-agent/security-reviews/2026-10-02-operator-evidence-review6.md`, and
  the D4.2 `execstart_sha256` in `review-7/bundle-box.json`. Copy it with `pbcopy` and read it on the box with
  `read -r -p`, never typed into a block.
- D10.8 needs a chat audit that returned `ok` within 7 days of the collection. The last one was 2026-10-05.
- D10.7's three live refusal checks were last run 2026-10-02 and are good for 30 days.
- Collect both bundles and sign on the same UTC day. Re-collect the laptop bundle if the evidence is corrected
  later, and the box bundle after any change to the box.
- D10.5: capture the whole privacy page and the key's page, state where the key is stored, and search the
  laptop for a copy before stating that it is dedicated.
- The summary script for a trial collection is not in the repo. It prints, from the bundle: each item's status;
  D4.1 `listeners`, `docker_dns_listeners` and `secret_env`; each labelled D2.1 row (label, kind, owner, mode,
  `secrets_held`, `credential_shaped_names`); D10.8 `out_of_whitelist` and the count of `run`/`ok` rows.

## Rules that apply

- No push and no PR without the operator's word; the operator merges.
- Build work: plan, implementer, independent review, then ask before pushing.
- Any change under `infra/hermes-agent/bin/` or `deploy/` changes the box fingerprint. Any change to
  `CHECKLIST.md` bumps the version above 1.16.
- Verify against primary sources before an important decision, and record them in `docs/evaluations/`. Inspect
  what a new Hermes version writes and listens on before trusting it.
- Never put a client name, customer id, hostname, fingerprint or credential value in the repo, the brain or the
  conversation. Label every block VPS / LAPTOP / HERMES CHAT, one paste per block. Ask the operator to paste
  output without the shell prompt (it carries the hostname), and to type an address or an id only at a `read`
  prompt.
- The project's secret-read guard blocks the agent from reading `.env` files. Give the operator a command that
  prints names and yes/no only.
