# Hermes v0.21.5: keep the API server off, inventory its key, and catch new listeners — Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Stay on Hermes v0.21.5 and later with the reviewed posture: the gateway's API server stays off, the key v0.21.5 generates is an inventoried, leak-checked secret, and every security review measures the gateway container's listening ports, so a future upstream default that opens a listener fails the review instead of passing unseen.

**Spec (measured 2026-10-05, v0.21.5 image `sha256:fca358f1…52b7`):**
- `docker/stage2-hook.sh` seeds `$HERMES_HOME/.env` (`/opt/data/.env`, on the box `/opt/projects/claude_code/infra/hermes-agent/data/.env`, owner uid 10000, mode 0600) from the bundled 26 KB `.env.example` (11 non-secret default assignments) and, when no `API_SERVER_KEY` exists in the container environment or in that file, appends a generated `API_SERVER_KEY` (64 hex). Hermes loads that file with `override=True`.
- The gateway starts its API server on `127.0.0.1:8642` inside the container whenever `API_SERVER_KEY` has 16 or more characters (`gateway/config_env.py:_api_server`), **unless** `config.yaml` sets `enabled` for the platform: `_enable_from_env` enables a platform from env credentials "unless config.yaml explicitly disabled it" (`gateway/config_loader.py:merge_platform_sections` sets the explicit marker for any `enabled` key).
- Measured on the laptop with our derived image and our `config.yaml.example`: without the setting, port 8642 listens; with top-level `platforms: {api_server: {enabled: false}}`, nothing listens, and the block survives the gateway's rewrite of `config.yaml`. The key is generated either way.

## Global Constraints

- Worktree `/Users/ericksicard/Projects/claude_code/.claude/worktrees/api-off`, branch `fix/hermes-api-server-off`. Python stdlib only; no new file under `bin/` or `deploy/`.
- Nothing printed carries a value; names, labels, ports and counts only. Unmeasurable is `could-not-check`.
- `CHECKLIST.md` goes to `version: 1.16`, edited by exact substring, items stay one line each.
- The D10.6 pinned `mcp_servers` canonical sha256 must not change (`security-review-checklist.test.py` pins it): only add a new top-level key to `config.yaml.example`, never touch its `mcp_servers` block.
- No client name, customer id, hostname, credential value; no hash taken from a real system other than the image digest already in the repo.
- `infra/hermes-agent/bin/run-bin-tests.sh` and `node scripts/run-all-tests.js` pass. Commits end `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. No push, no PR.

---

### Task 1: The switch, the inventory and the listener check

**Files:** `infra/hermes-agent/config.yaml.example`, `infra/hermes-agent/bin/collect-review-evidence.py`, its test, `infra/hermes-agent/deploy/security-review/CHECKLIST.md`, `infra/hermes-agent/SECURITY-AUDIT.md`, `infra/hermes-agent/deploy/BRING-UP.md`, `docs/evaluations/2026-10-03-hermes-v0-21-5-upgrade-evaluation.md`.

- [ ] **1. config.yaml.example.** Append a top-level block, with a two-line comment saying why (v0.21.5+ generates an `API_SERVER_KEY` and would start the OpenAI-compatible API server on container loopback; our posture keeps it off, measured by review item D4.1 `listeners`):
  ```yaml
  platforms:
    api_server:
      enabled: false
  ```
  Then confirm `python3 infra/hermes-agent/bin/security-review-checklist.test.py` still passes unchanged, and that `mcp_config.compare(text, text)` on the new template still reports `equals_repo: true` (the new key must be a plain top-level key).

- [ ] **2. Collector, D2.1 inventory.** Authorise the Hermes home secrets file: `HERMES_HOME_ENV_FILE = CHECKOUT + "/infra/hermes-agent/data/.env"`, label `hermes-home-env` in `AUTHORISED_OTHER`, and `OTHER_SECRET_NAMES[HERMES_HOME_ENV_FILE] = (("API_SERVER_KEY", "api-server-key"),)`, so its value joins the known secrets (leak checks, the output guard) and the credential set (with a sha12: it is a random 64-hex key). On that file's D2.1 row only, add `credential_shaped_names`: the sorted assignment NAMES in the file (any `NAME=` line, `export ` allowed) that contain `KEY`, `TOKEN`, `SECRET`, `PASSWORD`, `PASSWD`, `CREDENTIAL` or `AUTH`, excluding `API_SERVER_KEY`. Names only, never values; read the file with the same tolerant single read `_other_secrets` uses. It catches a provider key placed there, where it would silently override the gateway's own `.env`.

- [ ] **3. Collector, D4.1 listeners.** In `d4_1`, after the existing `docker exec` calls, add one: `docker exec <gw> cat /proc/net/tcp /proc/net/tcp6` and report `listeners`: the sorted, de-duplicated decimal local ports of every socket in state `0A` (LISTEN). A non-zero exit, or output with no parsable header, makes `listeners` `could-not-check` without losing the rest of D4.1. No address or other field reaches the bundle.

- [ ] **4. Tests** (in `collect-review-evidence.test.py`, following the D4.1 and `_gateway_env` fixtures; each fails before the change):
  - the template on the box is `authorised-other` / `hermes-home-env` with `secrets_held: ["api-server-key"]`, `secrets_not_searchable: []`, `credential_shaped_names: []`; its key is in the returned secrets list, counted by D2.3 when it appears in the journal, absent from the bundle, and listed in `credentials` with a sha12;
  - the same file also holding `OPENROUTER_API_KEY=` and `GITHUB_TOKEN=` lines: `credential_shaped_names == ["GITHUB_TOKEN", "OPENROUTER_API_KEY"]` and no value in the bundle;
  - `listeners` from a fixture `/proc/net/tcp` with one LISTEN on 8642 (hex `21C2`), one ESTABLISHED, and a tcp6 LISTEN on 9119: `[8642, 9119]`; empty tables: `[]`; exec failure: `could-not-check`, other D4.1 fields still present.

- [ ] **5. CHECKLIST.md → v1.16.** Header note: `(v1.16: Hermes v0.21.5 — D2.1 the Hermes home secrets file \`hermes-home-env\` with the generated API server key; D4.1 \`listeners\`, the gateway container's listening ports.)`. D2.1 expected: a fourth authorised row, path `/opt/projects/claude_code/infra/hermes-agent/data/.env`, `kind: authorised-other`, `label: hermes-home-env`, owner `10000` (the gateway's uid; the collector prints the number when the host has no such user), mode `0o600`, `secrets_held: ["api-server-key"]`, `secrets_not_searchable: []`, `credential_shaped_names: []`; written by Hermes's start-up from its bundled template plus a generated `API_SERVER_KEY`; `credentials` then also lists `api-server-key` with a `sha12`. D2.1 pass rule: a non-empty `credential_shaped_names` is a FAIL (a credential in this file overrides the gateway's own environment). D4.1 expected: `listeners` is `[]`, or `[9119]` when the dashboard is switched on (the port D1.1 shows on the host's loopback); the API server (`8642`) must not listen: `config.yaml` carries `platforms.api_server.enabled: false`. D4.1 pass rule: any other port in `listeners` is a FAIL (a new upstream default that opens a listener must be decided, not inherited); `could-not-check` is CANNOT-VERIFY. Add `api-server-key` to D10.7's list of known secrets.

- [ ] **6. SECURITY-AUDIT.md.** In the re-audit section add a finding row: v0.21.5 generates an `API_SERVER_KEY` into `/opt/data/.env` and starts the API server on container loopback `127.0.0.1:8642` by default; mitigated by `platforms.api_server.enabled: false` in `config.yaml` (measured: no listener, the setting survives the gateway's rewrite); the key is inventoried (D2.1) and the listeners are measured on every review (D4.1). Extend checklist item 10 ("Re-run this audit on every version bump") with what the first v0.21.5 re-audit missed: diff `docker/stage2-hook.sh` against the previous pin; list what the first start writes into `/opt/data` (file names and assignment names only, never values); list the gateway container's listening ports.

- [ ] **7. BRING-UP.md.** In the "Ads audits on the box" or chat-trigger part where `data/config.yaml` is installed from the template, add one sentence: from Hermes v0.21.5 the template carries `platforms.api_server.enabled: false`; a box whose `data/config.yaml` predates it gets the block appended once (the gateway keeps it through its rewrites), then `sudo docker compose restart hermes-agent`.

- [ ] **8. Evaluation record.** Add a section "Missed at first, found on the box (2026-10-05)": the facts in this plan's Spec, the laptop measurement table (control vs disabled), and that the API server key is the only assignment the start-up adds to the template.

- [ ] **9. Verify and commit.** Both test runners pass; `check-checklist-version.py --base main` exits 0; no 12-hex string added outside the existing image digest. Commit: `fix(hermes): keep the v0.21.5 API server off, inventory its key, measure container listeners (checklist v1.16)`.
