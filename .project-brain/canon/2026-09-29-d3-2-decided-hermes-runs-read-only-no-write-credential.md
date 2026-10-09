---
type: decision
title: D3.2 decided: Hermes runs read-only, no write credential
description: Security review #1 D3.2 (2026-09-29): Hermes holds no write credential. The operator won't create another Google account
tags: []
timestamp: 2026-09-29T15:12:00
sources: [sessions/daily/2026-09-29.md]
status: canon
promoted_at: 2026-10-09
---

Security review #1 D3.2 (2026-09-29): Hermes holds no write credential. The operator won't create another Google account, because the ADMIN account is shared with another project, and hermes@ must stay READ_ONLY as the platform read backstop. The old ADMIN write token (sha12 b5aa4baf3310) is NOT revoked, because revoking any grant on the shared account could kill the other project's grant (canon rule 1). Every copy is destroyed instead (box 2026-09-27 F24, laptop 2026-09-29), as an accepted risk. F25: hermes@ had drifted to STANDARD; it was restored and re-measured READ_ONLY. Changes to client accounts belong to apps joining the AI OS; any future write role needs a dedicated STANDARD account plus a new security review. The mutation tier and the live gate are parked. PR #71.
