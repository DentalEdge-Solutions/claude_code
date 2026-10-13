---
name: ads-reports
description: Use when the operator asks to run, check, or list a client's Google Ads figures report. Calls the ads_report_run, ads_report_status and ads_report_list tools. Never reads or summarizes report content; the operator reads reports on the host. Not for audits: an audit request goes to the ads-audits skill.
---

# Client Google Ads figures reports

You can trigger a client's Google Ads figures report and report its outcome. A figures report holds
the numbers only, with no AI analysis. You never see the report's content, and you must not try to:
reports are read by the operator on the host.

## Tools

- `ads_report_run(client)`: starts a figures report for a registered client (its short name). It takes
  a few minutes. You get back a result, or `pending` with a `request_id`.
- `ads_report_status(request_id)`: checks a pending request. It files nothing.
- `ads_report_list(client)`: lists the timestamps of the client's past figures reports.

## Reporting a result

| status | What to tell the operator | Then |
|---|---|---|
| `ok` | the figures report is done, its timestamp `ts`, and that they can read it with `sudo show-report <client>` | stop |
| `refused` | it was refused, and the `reason` in plain words (`quota`: one report per client per day; `disabled`: reports are switched off; `inactive_client`: not an active client; `precheck`: the server refused before starting; `bad_request`, `duplicate`) | stop. **Never call the tool again for that client today.** |
| `failed` | it failed at step `reason` (e.g. `collect`, `read`, `store`, `timeout`, `interrupted`) | suggest the manual command `sudo run-client-audit <client> --figures`; do not retry |
| `busy` | another run (an audit or a figures report) is in progress on the server | offer to try later; do not loop |
| `pending` | it is still running, and the `request_id` | check with `ads_report_status` once, only when the operator asks |
| the tool call itself errors or times out (no `status` came back) | you got no answer; the figures report may still be running or may have finished | do NOT call `ads_report_run` again and do NOT suggest the manual command (it would start a second report). Call `ads_report_list` once and report the latest timestamp; the operator can read it with `sudo show-report <client>` |

The result's `vault_path` is where the report was stored and a list's `audits` holds the reports' timestamps: the two labels are shared with the audit tools. Report the timestamp `ts`; never open the path.

## Never

- Call `ads_report_run` twice for the same client in one conversation.
- Retry a `refused` or `failed` result.
- Write into or read from `/opt/data/spool` yourself, or use the terminal to reach the report system.
- Guess a client's short name. If unsure, ask the operator.
- Treat a tool error or timeout as a failed report.
- Start an audit when a figures report was asked for, or the reverse. If the operator's request could mean either, ask.
