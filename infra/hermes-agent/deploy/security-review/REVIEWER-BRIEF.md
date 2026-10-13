# Brief for the independent security reviewer

You are reviewing a production box you did not build. You receive ONLY:

1. `CHECKLIST.md` (this directory) — cite its `version:`.
2. The box bundle and the laptop bundle (JSON, redacted by design).
3. `docs/superpowers/specs/2026-09-21-vps-first-bring-up-findings.md`.
4. This brief (`REVIEWER-BRIEF.md`) and `REPORT-TEMPLATE.md` (this directory).
5. The operator evidence file: the statements and attachments the checklist asks the operator for. It holds the manual items' statements (D3.2, D8.1, D8.2, D9.1 and D10.5, with D10.5's console screens of the limit and the privacy settings), D2.1's statement about the Anthropic key, D2.1's statement about the dashboard (when the gateway row's `secrets_held` names `dashboard-password`) and the `ls` output showing the rollback backups gone, D4.2's baseline statement (when `matches_last_pass` is `null` or `false`), D4.6's statement of each restart since the last PASS, D10.3's statement of the jobs the box runs (with, when it applies, the statement that a declared job is not yet installed and is not under review, the explanation of a job that is installed and not declared or on disk only, the explanation of a `units_not_counted` or `on_disk_not_counted` above `0`, and each new job's install date from the rollout record), D1.7's statement of whose each key is, D2.4's date and time the journal's retention was raised and the journal service restarted (while `reach_days` is under 30), its statement of any other directory under `/var/log/journal` (whenever `other_directories` is above `0`, at any reach), its explanation of `usage.files` lower than `reach_days` (whenever it is so, at any reach), D1.7's statement of any `Match` block, outside `Include` or daemon option, the laptop keychain check (BRING-UP "A security review"), D10.8's statement, for each installed job, that the job's `ok` run was triggered from chat, and every other explanation an item asks for.
6. `infra/hermes-agent/config.yaml.example` at the reviewed commit, for D10.6: its `mcp_servers:` block is the committed block the box's is compared with. It now holds two servers (`ads_audit` and `ads_report`), three tools each.
7. The previous PASS report's header block (everything above its "Verdicts" heading) and its operator sign-off: the baselines an item compares with (the fingerprint and its components, the box bundle's collection time, the authorised credential set, the accepted SSH keys' short fingerprints, D1.7's `match_lines`, `include_elsewhere` and `daemon_options`, D2.3's `scanned_characters` and days covered, D10.3's jobs (`declared_apps`, `installed_apps` and any job installed since the last PASS, with its install date), D10.7's `oldest_entry_read` and days covered for each job, D2.4's oldest entry, retention and `Storage`, D4.2's `execstart_sha256` and `execstart_argv_sha256`, D4.5's `alert_log`, D7.1's `records` and its report store line). Nothing else of that report.

You do not receive the build conversation. Do not ask for it.

## Rules

- Judge every checklist item: `PASS`, `FAIL` or `CANNOT-VERIFY`. Quote the evidence (a short excerpt) for each.
- `could-not-check` evidence is `CANNOT-VERIFY`. Missing evidence is `CANNOT-VERIFY`. Never pass by default — ask the operator for more evidence instead.
- D10.3, D10.4, D10.7 and D10.8 are judged job by job: read every job's entry under `apps`, and never judge one of these items by its status word alone. An item can be reported as observed while one job's values are `could-not-check`: for an installed job that is `CANNOT-VERIFY` for the item. Each entry says whether its job is `declared` and `installed`; the checklist's D10 lead says how each case is judged.
- Anything alarming the checklist does not cover goes in **Not on the checklist**, with your recommendation.
- For D3.2 you may recommend a dedicated STANDARD-access account; the operator decides.
- The overall verdict is PASS only if every item is PASS (manual items: the operator's statement is the evidence).
- Customer-id fingerprints (`cid:`) are keyed (HMAC-SHA256, 12 hex): the key lives only on the operator's laptop. Both bundles carry a `cid_key_id`, and the two must show the same one. If they differ (or either is missing), every comparison of a `cid:` fingerprint across the bundles is `CANNOT-VERIFY`, never a mismatch. The box bundle also carries the last PASS's proxy `execstart_sha256` (D4.2 `last_pass_execstart_sha256`) as the baseline for D4.2.
- Never paste a client slug, a customer id or a credential value into the report — the bundles already hide them; keep it that way.

## Output

Write `docs/security-reviews/YYYY-MM-DD-review.md` from `REPORT-TEMPLATE.md`.
