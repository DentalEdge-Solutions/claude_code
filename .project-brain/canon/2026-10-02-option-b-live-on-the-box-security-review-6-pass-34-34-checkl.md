---
type: decision
title: Option B live on the box; security review 6 PASS 34/34 (checklist v1.14)
description: Option B (chat-triggered Google Ads audits, spec 2026-09-30) is live on the box and security review 6 is PASS 34/34 agai
tags: []
timestamp: 2026-10-02T17:32:00
sources: [sessions/daily/2026-10-02.md]
status: canon
promoted_at: 2026-10-02
---

Option B (chat-triggered Google Ads audits, spec 2026-09-30) is live on the box and security review 6 is PASS 34/34 against checklist v1.14 (report docs/security-reviews/2026-10-02-review-6.md, operator sign-off 2026-10-02, box checkout 6c4d08c). The rollout followed BRING-UP chat-triggered audits parts 1 and 2 on 2026-10-01 and 2026-10-02: client data out of the gateway, the Anthropic key in its own root-only file, the per-app broker and root runner, a dedicated OpenRouter key, then a manual audit, chat audits and the three live refusal checks. The first real run found three defects that tests against stand-ins had missed, each fixed and re-proven on the box before evidence was collected: the app MCP server did not answer Hermes's liveness ping while a call waited, so every chat audit's reply was lost (PR 92); review item D10.6 compared the MCP config line for line although the gateway rewrites that file's layout (PR 92, a strict parser compares values); and D4.2's proxy hash changes after a systemctl daemon-reload with the proxy untouched (PR 93). The lesson that earned this: an integration is not proven until it has run once against the real counterpart, and a trial evidence collection before the real one finds checklist rules that fail a healthy box. The read-only posture continues: one READ credential, no write credential, and the retired ADMIN token remains an accepted risk.
