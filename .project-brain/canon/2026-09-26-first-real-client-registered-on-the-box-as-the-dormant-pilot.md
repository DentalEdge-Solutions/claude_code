---
type: decision
title: First real client registered on the box as the dormant pilot — kill switch still absent
description: On 2026-09-26 the operator chose the authorised dormant pilot (zero spend, already the local test account for every earl
tags: []
timestamp: 2026-09-26T13:31:00
sources: [sessions/daily/2026-09-26.md]
status: canon
promoted_at: 2026-09-26
---

On 2026-09-26 the operator chose the authorised dormant pilot (zero spend, already the local test account for every earlier change-set and undo) as the first real client on the box, marked mutation_target=dormant_pilot so the live gate resolves it programmatically instead of anyone guessing. It had to be the account the WRITE credential is pinned to, because apply-changeset.py refuses unless the client's customer_id equals the credential's GOOGLE_ADS_CUSTOMER_ID; so the id was read from the credential file on the box, its sha12 matched the laptop audit, and clients.json was rebuilt from the current file keeping rehearsal retired. Results: 2 clients (active, retired), exactly 1 pilot, root:hermes 640, PILOT_OK, the pilot's log created and sealed append-only, pre-flight rc=0, kill switch absent. Gotcha: the Python library reads HERMES_GOVERNANCE_ROOT, not HERMES_GOVERNANCE_DIR (the wrapper's name), so the first resolver check fell back to /opt/governance; pass --registry explicitly. Next and last: the operator's decision to create the kill switch for the live gate, then remove it immediately after. Recorded in BRING-UP; slug kept off the repo per F21.
