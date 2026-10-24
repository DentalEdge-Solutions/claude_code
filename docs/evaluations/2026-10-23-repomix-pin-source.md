# Repomix pin: version source record (P0-01)

> Date: 2026-10-23 · Item: P0-01 (S5 roadmap), batch B1 PR-1 · Rule: `CLAUDE.md:76` (verify against primary sources, record each)

## Decision

`skills/repo-audit/SKILL.md` runs `npx -y repomix@1.18.1`. The policy was the latest stable release that is at least
14 days old. 1.18.1 is the latest release, 32 days old on 2026-10-23. It is also the only release patched for every
published Repomix advisory: GHSA-4p5g-gh74-q524 (High) affects every version up to and including 1.18.0. The
`pip install gitingest` fallback is removed, so the skill now stops when Repomix fails.

Repomix 1.18.1 declares `engines.node >=22.0.0`, so the skill's `compatibility` line now says Node.js ≥ 22.

No package was downloaded or run for this record. Only release notes, advisories and registry metadata were read.

## Sources (all accessed 2026-10-23)

| Source | Tier | What it verified |
|---|---|---|
| npm registry, `npm view repomix time --json` | A (official registry) | 86 published versions, none a prerelease. 1.18.1 was published 2026-09-21T08:27:33Z, which is 32 days before the access date and so clears the 14-day minimum. 1.18.0 was published 2026-08-04 |
| npm registry, `npm view repomix dist-tags --json` | A | `latest` = 1.18.1 |
| npm registry, `npm view repomix@1.18.1 …` | A | Not deprecated. `dist.integrity` = `sha512-XtV1qD6akJSigQ3fBRex5v+rWcGa4i9cm2FL/M/PEtzO3u1uDiso3CtNbhlZiMIqJstAdy8mj2m1ynOzNnNB3g==`. Two registry signatures (keyid `SHA256:DhQ8wR5APBvFHLF/+Tc+AYvPOdTpcIDqOhxsBHRwC7U`). Repository `github.com/yamadashy/repomix`. `engines.node` `>=22.0.0`. `bin` `repomix` |
| GitHub releases, https://github.com/yamadashy/repomix/releases | A (official repository) | v1.18.1 is marked Latest and is not a prerelease; none of the ten listed releases is a prerelease. The v1.18.1 notes include the fix for GHSA-4p5g-gh74-q524: Repomix no longer runs a target repository's own git config helpers |
| GitHub repository advisories, https://github.com/yamadashy/repomix/security/advisories | A (the maintainer's repository advisories) | 5 published advisories, listed below. These are the project's own advisories, not entries in the global GitHub Advisory Database (see the note below the table) |
| GHSA-4p5g-gh74-q524 (repository advisory) | A | High (CVSS 7.8 on the repository advisory). Code execution through a crafted `.git` config. Affected `>= 0.2.41, < 1.18.1`; patched in 1.18.1. Published 2026-09-21. No CVE |
| GHSA-w8cw-mgw9-74h7 (repository advisory) | A | Moderate. Credentials in remote URLs were logged. Affected `<= 1.17.0`; patched in 1.18.0 |
| GHSA-rpmv-562j-qxrv (repository advisory) | A | Low. MCP file system tools claimed protections they did not have. Affected `<= 1.17.0`; patched in 1.18.0 |
| GHSA-hwpp-h97w-2h3j (repository advisory) | A | Moderate. `attach_packed_output` bypassed the secret scan (CVE-2026-49988). Affected `<= 1.14.0`; patched in 1.14.1 |
| GHSA-9mm9-rqhj-j5mx (repository advisory and global database) | A | High. Command injection through `--remote-branch` (CVE-2026-49987). Affected `< 1.14.1`; patched in 1.14.1. The CVSS 8.8 (`CVSS:3.1/AV:N/AC:L/PR:N/UI:R/S:U/C:H/I:H/A:H`) is the global database entry's score, https://github.com/advisories/GHSA-9mm9-rqhj-j5mx. On the repository advisory, the body's "Severity" section says only "High"; a re-read on 2026-10-23 also showed the same vector and 8.8 in its metadata table |

**Repository advisory vs global database (checked 2026-10-23).** https://github.com/advisories/GHSA-4p5g-gh74-q524 returns
HTTP 404: the High advisory fixed in 1.18.1 is not in the global GitHub Advisory Database. So `npm audit` and
Dependabot, which read the global database, would not flag 1.18.0 for it. Read the repository's own advisories when
choosing a Repomix version. GHSA-9mm9-rqhj-j5mx is in the global database (reviewed, published 2026-05-27).

## Not verified

- The tarball was not downloaded, and its contents were not compared with the GitHub tag. The pin relies on the
  registry's integrity hash and signatures.
- Runtime behaviour of 1.18.1 against repo-audit's flags (`--remote`, `--compress`, `--output-format json|xml`) was
  not exercised here. It is measured in the first post-change repo-audit eval (P1-10, B6), as S5 P0-01 states.

## Revisit

Revisit when a new Repomix advisory is published, or when repo-audit needs a newer release. Apply the same policy:
latest stable, at least 14 days old, no open advisory. Record the new version in a new dated file.
