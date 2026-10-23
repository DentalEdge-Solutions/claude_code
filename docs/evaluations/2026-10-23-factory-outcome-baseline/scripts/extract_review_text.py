#!/usr/bin/env python3
"""P1-01: pull the review-related lines out of the fetched PR bodies, as the input to the hand coding
in review-coding-manual.csv. No git or GitHub calls.

Usage: python3 -I extract_review_text.py <data-dir>
Writes <data-dir>/review-excerpts.txt (every PR merged since 2026-08-01, matching lines only) and
<data-dir>/review-context.txt (candidate PRs, matching lines with one line before and two after).
The coder then read the full body of any PR whose excerpt was ambiguous (done for #19, #20, #23).
"""
import glob, json, os, re, sys

DATA = sys.argv[1]
files = sorted(glob.glob(os.path.join(DATA, "pr-bodies", "*.json")), key=lambda x: int(os.path.basename(x)[:-5]))
with open(os.path.join(DATA, "review-excerpts.txt"), "w") as out:
    for f in files:
        d = json.load(open(f)); b = d["body"] or ""
        if d["mergedAt"] < "2026-08-01":
            continue
        out.write(f"===== {d['number']} {d['mergedAt'][:10]} {d['title'][:100]} | gh-reviews: {len(d['reviews'])} gh-comments: {len(d['comments'])}\n")
        for l in b.splitlines():
            if re.search(r"(?i)review|\bround|finding|blocking|blocker|approv|re-check|recheck", l):
                out.write("    " + l.strip()[:400] + "\n")

CAND = [5, 7, 8, 16, 19, 20, 23, 25, 26, 27, 30, 35, 42, 57, 61, 62, 69, 75, 85, 86, 96, 97, 99, 100, 102, 105, 107,
        114, 115, 120, 121, 123, 130, 131, 132, 133, 134, 135, 136, 138, 141, 142, 143, 144, 145, 146, 147, 149, 150,
        151, 152, 154, 155, 156, 157, 158, 159, 160, 161, 162, 163, 164, 165, 166, 167, 168, 169, 170, 171, 172, 173, 174]
kw = re.compile(r"(?i)review|\bround|finding|blocking|blocker|approv|re-check|critical|important|minor|verdict|fix wave|fix round")
with open(os.path.join(DATA, "review-context.txt"), "w") as out:
    for n in CAND:
        d = json.load(open(os.path.join(DATA, "pr-bodies", f"{n}.json"))); L = (d["body"] or "").splitlines()
        keep = set()
        for i, l in enumerate(L):
            if kw.search(l):
                keep.update(range(max(0, i - 1), min(len(L), i + 3)))
        out.write(f"===== {n} {d['title'][:100]}\n")
        last = -2
        for i in sorted(keep):
            if i != last + 1:
                out.write("   ...\n")
            out.write("    " + L[i][:600] + "\n"); last = i

# second pass used to find review signals missed by the first keyword set, in PRs not in CAND
kw2 = re.compile(r"(?i)independent|reviewer|opus|subagent|verifier|whole-branch|per-task|fix wave|fix round|code review|\bR\d+\b")
with open(os.path.join(DATA, "review-missed-check.txt"), "w") as out:
    for f in files:
        d = json.load(open(f))
        if d["mergedAt"] < "2026-08-01" or d["number"] in CAND:
            continue
        hits = [l.strip()[:250] for l in (d["body"] or "").splitlines() if kw2.search(l)]
        out.write(f"{d['number']} {d['title'][:70]} | hits: {len(hits)}\n")
        for h in hits[:4]:
            out.write("      " + h + "\n")
