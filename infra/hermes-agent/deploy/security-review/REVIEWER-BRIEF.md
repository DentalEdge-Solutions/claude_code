# Brief for the independent security reviewer

You are reviewing a production box you did not build. You receive ONLY:

1. `CHECKLIST.md` (this directory) — cite its `version:`.
2. The box bundle and the laptop bundle (JSON, redacted by design).
3. `docs/superpowers/specs/2026-09-21-vps-first-bring-up-findings.md`.
4. This brief (`REVIEWER-BRIEF.md`) and `REPORT-TEMPLATE.md` (this directory).
5. The operator evidence file: the statements and attachments the checklist asks the operator for. It holds the manual items' statements (D3.2, D8.1, D8.2, D9.1 and D10.5, with D10.5's console screens of the limit and the privacy settings), D2.1's statement about the Anthropic key, D2.1's statement about the dashboard (when the gateway row's `secrets_held` names `dashboard-password`) and the `ls` output showing the rollback backups gone, D4.2's baseline statement (when `matches_last_pass` is `null` or `false`), D10.8's statement that the `ok` run was triggered from chat, and every other explanation an item asks for.
6. `infra/hermes-agent/config.yaml.example` at the reviewed commit, for D10.6: its `mcp_servers:` block is the committed block the box's is compared with.

You do not receive the build conversation. Do not ask for it.

## Rules

- Judge every checklist item: `PASS`, `FAIL` or `CANNOT-VERIFY`. Quote the evidence (a short excerpt) for each.
- `could-not-check` evidence is `CANNOT-VERIFY`. Missing evidence is `CANNOT-VERIFY`. Never pass by default — ask the operator for more evidence instead.
- Anything alarming the checklist does not cover goes in **Not on the checklist**, with your recommendation.
- For D3.2 you may recommend a dedicated STANDARD-access account; the operator decides.
- The overall verdict is PASS only if every item is PASS (manual items: the operator's statement is the evidence).
- Customer-id fingerprints (`cid:`) are keyed (HMAC-SHA256, 12 hex): the key lives only on the operator's laptop. Both bundles carry a `cid_key_id`, and the two must show the same one. If they differ (or either is missing), every comparison of a `cid:` fingerprint across the bundles is `CANNOT-VERIFY`, never a mismatch. The box bundle also carries the last PASS's proxy `execstart_sha256` (D4.2 `last_pass_execstart_sha256`) as the baseline for D4.2.
- Never paste a client slug, a customer id or a credential value into the report — the bundles already hide them; keep it that way.

## Output

Write `docs/security-reviews/YYYY-MM-DD-review.md` from `REPORT-TEMPLATE.md`.
