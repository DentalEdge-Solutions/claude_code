---
type: decision
title: Tailscale is the one adoption from the external VPS guide — a second layer, not a replacement for auth
description: Evaluated the external Divisual 'Hermes Agent VPS + Claude Code' guide (337 lines) as reference material only; nothing e
tags: []
timestamp: 2026-09-19T16:10:00
sources: [sessions/daily/2026-09-19.md]
status: superseded
---

Evaluated the external Divisual 'Hermes Agent VPS + Claude Code' guide (337 lines) as reference material only; nothing executed. Tailscale is the single genuine adoption: canon 2026-07-21 line 46 and SECURITY-AUDIT.md:40,45 already sanction 'bind loopback + SSH/Tailscale tunnel, auth required for any public bind', and it has never been implemented. Adopt it as an ADDITIONAL layer alongside mandatory dashboard auth, explicitly rejecting the guide's 'hermes dashboard --insecure' shape: our own audit at :42-43 records that an unauthenticated dashboard/API was the entry point for the June 2026 attack that planted an SSH-key backdoor, so a network boundary must never be treated as an authentication boundary. Also rejected from the guide: 'curl install.sh | bash' as root (audit :23 already assessed and declined it in favour of the digest-pinned image), root-only operation with no deploy user, and 'git clone https://TOKEN@github.com/...' which writes the PAT into .git/config in plaintext. Design note carries four UNVERIFIED questions that must be MEASURED on a real host before anything is built — chiefly whether the Hermes Desktop app accepts basic auth at all, and whether Tailscale's presence makes provision.sh's check_firewall report false drift: docs/superpowers/specs/2026-09-19-tailscale-access-design.md. Proposal only, not approved, nothing built or deployed.
