---
type: decision
title: Security review defined and its tooling merged (PRs #68, #69) — app packages replace the deploy-key clone
description: The security review that real credentials and the ads code both waited on is now defined (spec 2026-09-28) and built (PR
tags: []
timestamp: 2026-09-29T12:15:00
sources: [sessions/daily/2026-09-29.md]
status: retired
---

The security review that real credentials and the ads code both waited on is now defined (spec 2026-09-28) and built (PR #69): an independent reviewer session judges a versioned checklist (D1-D9, v1.3) against evidence from two read-only, redacting collectors, the operator signs off, and a PASS binds to a three-part fingerprint (box state, authorised credential set, measured-access digest) that BRING-UP checks before the kill switch. App code reaches the box as a package pinned in the registry (claude_google_ads at 5826212, sha256 839b9d68b431), guard 7 refuses any mutator whose bytes differ and runs it with python -I; no GitHub key and no client data on the box. The WRITE credential stays off the box until a PASS. The firewall part of the fingerprint normalises counters, timestamps, Docker-managed chains and fail2ban bans, because raw output changed on every run; its stability must still be confirmed on the box by running --fingerprint-only twice. Next: install the package, recreate the gateway, collect, review.
