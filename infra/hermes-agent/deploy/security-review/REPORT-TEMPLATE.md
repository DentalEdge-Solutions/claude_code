# Security review — YYYY-MM-DD

- **Checklist version:** 
- **Reviewer:** (session / model) — did not build the box: yes
- **Box fingerprint:** `<sha256>` (complete: true|false) — components: `clients` `<8 hex>`, `packages` `<8 hex>`, `code` `<8 hex>`, `entry_points` `<8 hex>`, `checklist` `<8 hex>`
- **Box bundle `collected_at`:** `<UTC time>` (the next review gives it to the collector as `--last-pass-collected-at`)
- **Accepted SSH keys (D1.7):** (one line per key: account, `sha12`, and `no options` or `limited to the forward`)
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
- **D9 decisions:** (one line per finding: accepted (reason) | blocking)
- **Signed:** operator, date
