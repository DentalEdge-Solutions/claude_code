# Security review — YYYY-MM-DD

- **Checklist version:** 
- **Reviewer:** (session / model) — did not build the box: yes
- **Box fingerprint:** `<sha256>` (complete: true|false) — components: `clients` `<8 hex>`, `packages` `<8 hex>`, `code` `<8 hex>`, `entry_points` `<8 hex>`, `checklist` `<8 hex>`
- **Box bundle `collected_at`:** `<UTC time>` (the next review gives it to the collector as `--last-pass-collected-at`)
- **Accepted SSH keys (D1.7):** (one line per key: account, `sha12`, and `no options` or `limited to the forward`)
- **sshd as it runs (D1.7):** `match_lines` `<number>`, `include_elsewhere` `<number>`, `daemon_options` `listeners` `<number>` / `config_file_options` `<number>` / `setting_options` `<number>`
- **Journal (D2.4):** `oldest_entry.journal` `<UTC time>`, `reach_days` `<number>`; `MaxRetentionSec` `<value>` set by `<file>`; `Storage` `<value or null>`; `service.active` `<true/false>`, `config_changed_after_start` `<true/false>`; `usage.flushed_to_disk` `<true/false>`, `on_disk_age_seconds` `<number>`; `<bytes_percent_of_max_use>`% of the size limit, `<files_percent_of_max_files>`% of the file limit; `other_directories` `<number>`
- **Journal search (D2.3):** `scanned_characters` `<number>`, `undecodable_characters` `<number>`, `oldest_entry_read` `<UTC time>`; days covered `<number>` (state it whenever D2.4's `reach_days` is under 30)
- **Proxy (D4.2):** `execstart_sha256` `<sha256>`, `execstart_argv_sha256` `<sha256>` (the next review gives the first to the collector as `--last-pass-execstart`)
- **Listener check (D4.5):** `alert_log` `<as the bundle shows it>`
- **D7.1 `records`:** `<number>`
- **`cid_key_id`:** box `<8 hex>`, laptop `<8 hex>` — equal: yes|no (if not, no `cid:` fingerprint can be compared across the bundles)
- **Authorised credential set:** (the box bundle's `credentials`, one line each: a Google row is role, refresh-token sha12, client-id sha12; a non-Google row is label and sha12, or label alone for the dashboard password)
- **Measured-access digest:** `<sha256>`
- **Components changed since the last PASS:** (first review: n/a)

## Verdicts

| Item | Verdict | Evidence (short quote) | Note |
|---|---|---|---|
| D1.1 | | | |
| … | | | |

(One row per checklist item, in the checklist's order, from D1.1 to its last item: the row above is an example, not the list.)

## Not on the checklist

## Reviewer's overall verdict

PASS | NOT PASS — (one paragraph)

## Operator sign-off

- **Final verdict:** PASS | NOT PASS
- **D3.2 decision:** (ADMIN kept | replaced) — reason:
- **D4.6 restarts:** (one line per `true` in `started_after_last_pass`: what started, when, why)
- **D2.4 journal:** (only when `reach_days` is under 30: the UTC date and time the retention was raised and the journal service restarted; any other directory under `/var/log/journal` explained; `usage.files` lower than `reach_days` explained)
- **D1.7 sshd:** (only when `match_lines`, `include_elsewhere`, `config_file_options` or `setting_options` is not `0`: what each block, file or option sets)
- **D9 decisions:** (one line per finding: accepted (reason) | blocking)
- **Signed:** operator, date
