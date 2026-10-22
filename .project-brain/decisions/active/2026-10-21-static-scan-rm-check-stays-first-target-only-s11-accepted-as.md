---
type: decision
title: static-scan rm check stays first-target-only; S11 accepted as a known limit (2026-10-21)
description: static-scan.js rm-rf-root still reads only the first rm target; the owner accepted the misses (S11) on 2026-10-21, and the check is documented as a tripwire, not a boundary.
tags: [static-scan, skill-audit, security, rm-rf-root, known-limit]
timestamp: 2026-10-21T23:31:00
sources: [sessions/daily/2026-10-21.md]
status: active
promoted_at: 2026-10-22
---

The rm-rf-root check in skills/skill-audit/scripts/static-scan.js keeps reading only the first target of an rm command, and on 2026-10-21 the owner accepted this as a known limit (gap S11). It still BLOCKs, in prose, a first target that is an absolute or home path, /tmp and $HOME included (a FLAG when the command appears only in code, per the 2026-10-15 decision that severity depends on where a command appears); its only skip is git rm --cached. It misses a root or home path after the first target (rm -rf ./build ~/), options written after the target (rm / -rf) and a target built from a variable other than $HOME (rm -rf "$DIR"). Why accepted: an every-target regex froze the scanner and could be escaped (PR #138 final review F1-F4). A shell-aware detector was designed (docs/superpowers/specs/2026-10-21-s11-rm-every-target-design.md, not built); each of two independent design reviews found more disguises, and revision 2 closed round 1's. Variable targets are out of scope by design, since flagging every one would bury the reviewer. In a rough count on 3,016 real Markdown files, 1 of 5,076 rm commands with -r or -f had a root or home target after the first. skills/skill-audit/REFERENCE.md now says the check reads the first target only and is a tripwire, not a boundary: a skill is cleared by reading it (PR #168, merge 86677c6). Open follow-up: study known projects and best practices for this kind of static check before revisiting. This replaces decisions/superseded/2026-10-15-static-scan-rm-rf-root-checks-the-first-target-only-with-no-.md.
