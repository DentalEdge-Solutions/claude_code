---
type: decision
title: Real WRITE credential installed on the box — audited first, fingerprint-matched, kill switch still absent
description: On 2026-09-25 the real WRITE Google Ads credential was installed on the box as the gaw env file in /opt/hermes-agent (he
tags: []
timestamp: 2026-09-25T21:17:00
sources: [sessions/daily/2026-09-25.md]
status: canon
promoted_at: 2026-09-26
---

On 2026-09-25 the real WRITE Google Ads credential was installed on the box as the gaw env file in /opt/hermes-agent (hermes-broker:hermes-broker 0600), as its own deliberate step separate from the rehearsal. It was measured on the laptop before it left: audit-credential-access.sh rc=0, declared write = measured MUTATE_CAPABLE, manager-level ADMIN as expected for the operator's own account, and the read-only hermes@ account still READ_ONLY. On the box it was installed from the deploy user's home and the temporary copy shredded; role line = write, no REHEARSAL placeholder, and the refresh-token sha12 matched the laptop audit, so the installed file is the audited one, with no value printed on either side. The kill switch stays absent and no real client is registered; next is merging the first real client into clients.json beside the retired rehearsal entry with --bootstrap-logs --apply, then the operator's kill-switch decision. Recorded in BRING-UP 'Before creating the kill switch'.
