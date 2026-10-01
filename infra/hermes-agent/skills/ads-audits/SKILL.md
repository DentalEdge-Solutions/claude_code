---
name: ads-audits
description: Use when the operator asks to run, check, or list a client's Google Ads audit. Calls the ads_audit_run, ads_audit_status and ads_audit_list tools. Never reads or summarizes audit content; the operator reads drafts on the host.
---

# Client Google Ads audits

You can trigger a client's Google Ads trend audit and report its outcome. You never see the
audit's content, and you must not try to: drafts are read by the operator on the host.

## Tools

- `ads_audit_run(client)`: starts an audit for a registered client (its short name). It takes
  a few minutes. You get back a result, or `pending` with a `request_id`.
- `ads_audit_status(request_id)`: checks a pending request. It files nothing.
- `ads_audit_list(client)`: lists the timestamps of the client's past audits.

## Reporting a result

| status | What to tell the operator | Then |
|---|---|---|
| `ok` | the audit is done, its timestamp `ts`, and that they can read it with `sudo show-audit <client>` | stop |
| `refused` | it was refused, and the `reason` in plain words (`quota`: one audit per client per day; `disabled`: audits are switched off; `inactive_client`: not an active client; `precheck`: the server refused before starting; `bad_request`, `duplicate`) | stop. **Never call the tool again for that client today.** |
| `failed` | it failed at step `reason` (e.g. `collect`, `draft`, `timeout`, `interrupted`) | suggest the manual command `sudo run-client-audit <client>`; do not retry |
| `busy` | another audit is running on the server | offer to try later; do not loop |
| `pending` | it is still running, and the `request_id` | check with `ads_audit_status` once, only when the operator asks |

## Never

- Call `ads_audit_run` twice for the same client in one conversation.
- Retry a `refused` or `failed` result.
- Write into or read from `/opt/data/spool` yourself, or use the terminal to reach the audit system.
- Guess a client's short name. If unsure, ask the operator.
