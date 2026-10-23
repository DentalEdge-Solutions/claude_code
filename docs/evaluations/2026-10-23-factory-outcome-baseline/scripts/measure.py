#!/usr/bin/env python3
"""P1-01 B0 outcome baseline: compute metrics 1-5 from git (read-only) and fetched PR JSON.

Usage: python3 -I measure.py <repo-dir> <head-sha> <data-dir>

Read-only on the repository: only `git rev-parse`, `git log`, `git diff`, `git ls-tree`,
`git cat-file`, `git merge-base --is-ancestor`. Writes only into <data-dir>.
Inputs in <data-dir>: prs-merged-all.json, pr-bodies/<n>.json (from fetch.sh), and the one
hand-coded input this script reads, review-coding-manual.csv (metrics 1, 4 and numbered findings).
The other two hand-coded inputs (spec-plan-match-verification-manual.csv,
fix-attribution-validation-manual.csv) are read by verify.py.
"""
import csv, json, os, re, statistics, subprocess, sys
from datetime import datetime, timezone

REPO, HEAD, DATA = sys.argv[1], sys.argv[2], sys.argv[3]
WINDOW_START = "2026-08-01T00:00:00Z"          # population: PRs merged at/after this (UTC)
DAY = 86400
FIX_RE = re.compile(r"^fix(\([^)]*\))?!?:")    # conventional-commit fix subject
FIX_TITLE_RE = re.compile(r"^fix\b", re.I)     # PR-level variant: title starts with fix / Fix
EXCLUDE_GREP = "infra/hermes-agent/data"       # never read; asserted absent from all path sets


def git(*args):
    return subprocess.run(["git", "-C", REPO, *args], check=True, capture_output=True,
                          text=True, errors="replace").stdout


def ts(iso):
    return int(datetime.strptime(iso, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc).timestamp())


def iso(t):
    return datetime.fromtimestamp(t, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def quart(xs):
    xs = sorted(xs)
    if not xs:
        return {}
    q = statistics.quantiles(xs, n=4, method="inclusive") if len(xs) > 1 else [xs[0]] * 3
    return {"n": len(xs), "min": xs[0], "p25": q[0], "median": q[1], "p75": q[2],
            "p90": statistics.quantiles(xs, n=10, method="inclusive")[8] if len(xs) > 1 else xs[0],
            "max": xs[-1], "mean": round(sum(xs) / len(xs), 2)}


head_full = git("rev-parse", HEAD).strip()
head_time = int(git("log", "-1", "--format=%ct", head_full).strip())

# ---------------------------------------------------------------- PRs and their merges
prs_all = json.load(open(os.path.join(DATA, "prs-merged-all.json")))
bodies = {}
for p in prs_all:
    with open(os.path.join(DATA, "pr-bodies", f"{p['number']}.json")) as f:
        bodies[p["number"]] = json.load(f)

pr = {}
for p in prs_all:
    n = p["number"]
    m = p["mergeCommit"]["oid"]
    t_merge = ts(p["mergedAt"])
    if t_merge > head_time:
        continue  # merged after the measured SHA
    anc = subprocess.run(["git", "-C", REPO, "merge-base", "--is-ancestor", m, head_full]).returncode == 0
    parents = git("log", "-1", "--format=%P", m).split()
    pr[n] = {"number": n, "title": p["title"], "mergedAt": p["mergedAt"], "t_merge": t_merge,
             "merge": m, "ancestor_of_head": anc, "parents": len(parents), "head": p["headRefName"],
             "gh_additions": p["additions"], "gh_deletions": p["deletions"], "gh_changed": p["changedFiles"],
             "body": bodies[n].get("body") or ""}

# files and lines each PR brought to main = diff of the merge against its first parent
for n, d in pr.items():
    base = d["merge"] + "^1"
    # path set for attribution: old and new name of a moved file both count (--no-renames)
    files = [l for l in git("diff", "--name-only", "--no-renames", base, d["merge"]).splitlines() if l]
    # size: renames detected (-M, git's default similarity), as GitHub counts them
    add = dele = binf = nchanged = 0
    for l in git("diff", "--numstat", "-M", base, d["merge"]).splitlines():
        a, b, _ = l.split("\t", 2)
        nchanged += 1
        if a == "-":
            binf += 1
        else:
            add += int(a); dele += int(b)
    assert not any(f.startswith(EXCLUDE_GREP) for f in files), n
    d.update(files=files, additions=add, deletions=dele, binary_files=binf, changed=nchanged,
             docs_only=all(f.endswith(".md") for f in files))

# commits each merge landed on main (first-parent merges): rev-list M^1..M^2
commits = {}
for n, d in pr.items():
    rng = f"{d['merge']}^1..{d['merge']}" if d["parents"] == 1 else f"{d['merge']}^1..{d['merge']}^2"
    out = git("log", "--no-merges", "--no-renames", "--format=%x01%H%x02%ct%x02%s%x02%B%x03", "--name-only", rng)
    for chunk in out.split("\x01")[1:]:
        meta, _, names = chunk.partition("\x03")
        sha, ct, subj, msg = meta.split("\x02", 3)
        commits[sha] = {"sha": sha, "ct": int(ct), "subject": subj, "message": msg, "landing_pr": n,
                        "t_land": d["t_merge"], "files": [x for x in names.splitlines() if x]}

pop = sorted(n for n, d in pr.items() if d["mergedAt"] >= WINDOW_START)


def refs(text, n):
    return re.search(r"(?<![\w/#])#%d\b" % n, text) is not None


# ---------------------------------------------------------------- metric 2 / 5: post-merge fixes
fix_commits = [c for c in commits.values() if FIX_RE.match(c["subject"])]
fix_prs = [d for d in pr.values() if FIX_TITLE_RE.match(d["title"])]
per_pr = []
for n in pop:
    d = pr[n]; fx = set(d["files"]); fx_code = {f for f in fx if not f.endswith(".md")}
    row = {"pr": n, "mergedAt": d["mergedAt"], "title": d["title"][:90], "docs_only": d["docs_only"],
           "changed_files": d["changed"], "additions": d["additions"], "deletions": d["deletions"],
           "lines_changed": d["additions"] + d["deletions"]}
    for W in (7, 30):
        complete = d["t_merge"] + W * DAY <= head_time
        row[f"window{W}_complete"] = complete
        c_in = [c for c in fix_commits if c["landing_pr"] != n and 0 < c["t_land"] - d["t_merge"] <= W * DAY]
        p_in = [y for y in fix_prs if y["number"] != n and 0 < y["t_merge"] - d["t_merge"] <= W * DAY]
        path = [c for c in c_in if fx & set(c["files"])]
        path_code = [c for c in c_in if fx_code & set(c["files"])]
        ref = [c for c in c_in if refs(c["message"], n)]
        ppath = [y for y in p_in if fx & set(y["files"])]
        ppath_code = [y for y in p_in if fx_code & set(y["files"])]
        pref = [y for y in p_in if refs(y["title"] + "\n" + y["body"], n)]
        # landing-PR reference: a later PR (any title) that lands >=1 fix(...) commit and whose title/body cites #n
        landref = sorted({c["landing_pr"] for c in c_in if refs(pr[c["landing_pr"]]["title"] + "\n" + pr[c["landing_pr"]]["body"], n)})
        row[f"landref_{W}d"] = len(landref)
        row[f"landref_{W}d_ids"] = " ".join(map(str, landref))
        row[f"fixc_path_{W}d"] = len(path)
        row[f"fixc_pathcode_{W}d"] = len(path_code)
        row[f"fixc_ref_{W}d"] = len(ref)
        row[f"fixpr_path_{W}d"] = len(ppath)
        row[f"fixpr_pathcode_{W}d"] = len(ppath_code)
        row[f"fixpr_ref_{W}d"] = len(pref)
        row[f"fixpr_path_{W}d_ids"] = " ".join(str(y["number"]) for y in ppath)
        row[f"fixpr_ref_{W}d_ids"] = " ".join(str(y["number"]) for y in pref)
    per_pr.append(row)

def share(rows, key, W):
    full = [r for r in rows if r[f"window{W}_complete"]]
    hit = [r for r in full if r[key] > 0]
    return {"complete_window_prs": len(full), "prs_with_>=1": len(hit),
            "share": round(len(hit) / len(full), 3) if full else None,
            "events_total": sum(r[key] for r in full),
            "censored_prs": len(rows) - len(full)}

m2 = {}
for W in (7, 30):
    for k in ("fixc_path", "fixc_pathcode", "fixc_ref", "fixpr_path", "fixpr_pathcode", "fixpr_ref", "landref"):
        m2[f"{k}_{W}d"] = share(per_pr, f"{k}_{W}d", W)
        m2[f"{k}_{W}d_code_prs_only"] = share([r for r in per_pr if not r["docs_only"]], f"{k}_{W}d", W)

# literal 10-14 proxy: fix(...) commits landing in the last 60 days before HEAD that reference
# (#N in the commit message, or in the landing PR's title/body) a PR merged in the 7 days before the commit landed
proxy = {"window": [iso(head_time - 60 * DAY), iso(head_time)], "fix_commits_in_window": 0,
         "referencing_pr_merged_prior_7d_commit_msg": 0, "referencing_pr_merged_prior_7d_landing_pr_text": 0}
for c in fix_commits:
    if head_time - 60 * DAY < c["t_land"] <= head_time:
        proxy["fix_commits_in_window"] += 1
        recent = [n for n, d in pr.items() if 0 < c["t_land"] - d["t_merge"] <= 7 * DAY and n != c["landing_pr"]]
        if any(refs(c["message"], n) for n in recent):
            proxy["referencing_pr_merged_prior_7d_commit_msg"] += 1
        lp = pr[c["landing_pr"]]
        hit = [n for n in recent if refs(lp["title"] + "\n" + lp["body"], n)]
        if hit:
            proxy["referencing_pr_merged_prior_7d_landing_pr_text"] += 1
            proxy.setdefault("landing_pr_to_referenced_prs", {})[str(c["landing_pr"])] = sorted(hit)
        if any(refs(c["message"], n) for n in recent):
            proxy.setdefault("commit_msg_refs", []).append({"sha": c["sha"][:12], "landing_pr": c["landing_pr"],
                                                            "refs": [n for n in recent if refs(c["message"], n)]})
proxy["fix_commits_total_since_2026-08-01"] = sum(1 for c in fix_commits if c["t_land"] >= ts(WINDOW_START))
proxy["fix_prs_since_2026-08-01"] = sum(1 for y in fix_prs if y["mergedAt"] >= WINDOW_START)

# ---------------------------------------------------------------- metric 5: size per PR
def sizes(rows):
    return {"changed_files": quart([r["changed_files"] for r in rows]),
            "lines_changed": quart([r["lines_changed"] for r in rows]),
            "additions": quart([r["additions"] for r in rows]),
            "deletions": quart([r["deletions"] for r in rows])}
m5 = {"all": sizes(per_pr), "code_touching": sizes([r for r in per_pr if not r["docs_only"]]),
      "docs_only": sizes([r for r in per_pr if r["docs_only"]]),
      "n_docs_only": sum(r["docs_only"] for r in per_pr), "n_code_touching": sum(not r["docs_only"] for r in per_pr),
      "gh_vs_git_mismatch": [n for n in pop if (pr[n]["gh_additions"], pr[n]["gh_deletions"], pr[n]["gh_changed"])
                             != (pr[n]["additions"], pr[n]["deletions"], pr[n]["changed"])],
      "gh_vs_git_checked_fields": ["additions", "deletions", "changedFiles"]}

# definition count, discovered dynamically at HEAD
def tree(path, recursive=False, dirs_only=False):
    a = ["ls-tree", "--name-only"] + (["-r"] if recursive else []) + (["-d"] if dirs_only else []) + [head_full, path]
    try:
        return [l for l in git(*a).splitlines() if l]
    except subprocess.CalledProcessError:
        return []
defs = {
    "skills/* (dirs)": len(tree("skills/", dirs_only=True)),
    ".claude/agents/*.md": len([x for x in tree(".claude/agents/") if x.endswith(".md")]),
    ".claude/agents/*.md excluding *-EVAL.md and *-REFINE-LOG.md": len([x for x in tree(".claude/agents/") if x.endswith(".md") and not re.search(r"-(EVAL|REFINE-LOG)\.md$", x)]),
    ".claude/skills/* (entries)": len(tree(".claude/skills/")),
    "packs/*/skills/* (entries)": sum(len(tree(p + "/skills/")) for p in tree("packs/", dirs_only=True)),
    "infra/hermes-agent/skills/* (entries)": len(tree("infra/hermes-agent/skills/")),
}
defs_lists = {"skills": tree("skills/", dirs_only=True), ".claude/agents": tree(".claude/agents/"),
              ".claude/skills": tree(".claude/skills/"),
              "packs": {p: tree(p + "/skills/") for p in tree("packs/", dirs_only=True)},
              "infra/hermes-agent/skills": tree("infra/hermes-agent/skills/")}

# footprint metric, skill-eval's definition (skills/skill-eval/SKILL.md:96 at cbb6d4e):
#   "Context Footprint = total lines across all files loaded on trigger + estimated tokens (lines x 4 avg)"
# and step 1 (SKILL.md:21): "read skills/<skill-name>/SKILL.md and all bundled files (REFERENCE.md, scripts/,
#   references/). Note every file that gets loaded when the skill triggers -- these all count toward context footprint."
# Variant A (step-1 literal): SKILL.md + REFERENCE.md + references/** + scripts/**.
# Variant B (SKILL.md only): the file Claude Code loads when the skill triggers; what committed SKILL-EVAL reports used.
# Lines = newline count of the blob at HEAD (wc -l). Report files (SKILL-EVAL.md, SKILL-AUDIT.md, *-REFINE-LOG.md),
# assets/ and other files are not counted. Binary blobs (NUL byte) are skipped and counted.
def blob_lines(path):
    data = subprocess.run(["git", "-C", REPO, "cat-file", "-p", f"{head_full}:{path}"], check=True,
                          capture_output=True).stdout
    return None if b"\0" in data else data.count(b"\n")

def footprint(skill_dir):
    files = tree(skill_dir + "/", recursive=True)
    a_files = [f for f in files if f in (skill_dir + "/SKILL.md", skill_dir + "/REFERENCE.md")
               or f.startswith(skill_dir + "/references/") or f.startswith(skill_dir + "/scripts/")]
    a = b = 0; skipped = 0
    for f in a_files:
        n = blob_lines(f)
        if n is None:
            skipped += 1; continue
        a += n
        if f == skill_dir + "/SKILL.md":
            b = n
    rep = None
    if skill_dir + "/SKILL-EVAL.md" in files:
        m = re.search(r"Context Footprint\s*\|\s*(\d+)\s*(?:L|lines)", git("show", f"{head_full}:{skill_dir}/SKILL-EVAL.md"))
        rep = int(m.group(1)) if m else None
    return {"skill": skill_dir, "has_skill_md": (skill_dir + "/SKILL.md") in files,
            "lines_skill_md": b, "tokens_skill_md": b * 4,
            "lines_bundled": a, "tokens_bundled": a * 4, "files_bundled": len(a_files) - skipped,
            "binary_skipped": skipped, "skill_eval_report_lines": rep}

skill_dirs = {"skills": tree("skills/", dirs_only=True), ".claude/skills": tree(".claude/skills/", dirs_only=True),
              "packs": [d for p in tree("packs/", dirs_only=True) for d in tree(p + "/skills/", dirs_only=True)],
              "infra/hermes-agent/skills": tree("infra/hermes-agent/skills/", dirs_only=True)}
fp_rows = [dict(footprint(d), location=loc) for loc, ds in skill_dirs.items() for d in ds]
fp = {"definition": "skills/skill-eval/SKILL.md:96 (lines x 4 tokens) and :21 (files counted)",
      "by_location": {}}
for loc in skill_dirs:
    rs = [r for r in fp_rows if r["location"] == loc and r["has_skill_md"]]
    fp["by_location"][loc] = {"skills": len(rs),
                              "skill_md_lines": quart([r["lines_skill_md"] for r in rs]),
                              "skill_md_lines_total": sum(r["lines_skill_md"] for r in rs),
                              "bundled_lines": quart([r["lines_bundled"] for r in rs]),
                              "bundled_lines_total": sum(r["lines_bundled"] for r in rs),
                              "binary_skipped": sum(r["binary_skipped"] for r in rs)}
rep = [r for r in fp_rows if r["skill_eval_report_lines"] is not None]
fp["committed_skill_eval_reports"] = {"with_parsable_footprint": len(rep),
                                      "equal_to_skill_md_lines_at_head": sum(r["skill_eval_report_lines"] == r["lines_skill_md"] for r in rep),
                                      "equal_to_bundled_lines_at_head": sum(r["skill_eval_report_lines"] == r["lines_bundled"] for r in rep)}

# ---------------------------------------------------------------- metric 3: spec/plan -> implementing PR
def first_add(path):
    out = git("log", "--follow", "--diff-filter=A", "--format=%H %ct %at", head_full, "--", path).split()
    if not out:
        return None
    sha, ct, at = out[-3:]
    return sha, int(ct), int(at)

def slug(base):
    s = re.sub(r"^\d{4}-\d{2}-\d{2}-", "", base[:-3] if base.endswith(".md") else base)
    s = re.sub(r"-(design|plan|spec|implementation)$", "", s)
    return s

def norm(s):
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")

sp_rows = []
non_sdocs = lambda d: any(not f.startswith("docs/superpowers/") for f in d["files"])
for kind in ("specs", "plans"):
    for path in tree(f"docs/superpowers/{kind}/", recursive=True):
        if not path.endswith(".md") or os.path.basename(path).lower() == "readme.md":
            continue
        archived = "/archive/" in path
        base = os.path.basename(path); sl = slug(base)
        fa = first_add(path)
        row = {"kind": kind[:-1], "path": path, "archived": archived, "slug": sl}
        if not fa:
            row.update(match="no-first-commit"); sp_rows.append(row); continue
        sha, ct, at = fa
        row.update(first_commit=sha[:12], first_commit_time=iso(ct), first_commit_author_time=iso(at),
                   landed_by_pr=commits.get(sha, {}).get("landing_pr"))
        cands = []
        for n, d in pr.items():
            if d["t_merge"] < ct or not non_sdocs(d):
                continue
            text = d["title"] + "\n" + d["body"]
            how = []
            if base in text or base[:-3] in text:
                how.append("body-names-file")
            if len(sl) >= 6 and norm(sl) in norm(d["head"]):
                how.append("branch-contains-slug")
            if row["landed_by_pr"] == n:
                how.append("same-pr-as-file")
            if how:
                cands.append((d["t_merge"], n, "+".join(how)))
        if cands:
            # priority: a PR whose body/title names the file, then a branch carrying the slug,
            # then the PR that landed the file; earliest merge within the best priority class
            prio = lambda c: 0 if "body-names-file" in c[2] else (1 if "branch-contains-slug" in c[2] else 2)
            earliest = min(cands)
            t, n, how = min(cands, key=lambda c: (prio(c), c[0]))
            row.update(earliest_rule_pr=earliest[1], earliest_rule_days=round((earliest[0] - ct) / DAY, 2))
            row.update(match=how, implementing_pr=n, merged_at=pr[n]["mergedAt"],
                       days=round((t - ct) / DAY, 2), days_from_author_time=round((t - at) / DAY, 2),
                       n_candidates=len(cands), other_candidates=" ".join(str(c[1]) for c in sorted(cands)[1:6]))
        else:
            row.update(match="unmatched")
        sp_rows.append(row)

def m3_summary(rows):
    m = [r for r in rows if r.get("implementing_pr")]
    return {"files": len(rows), "matched": len(m), "match_rate": round(len(m) / len(rows), 3) if rows else None,
            "days": quart([r["days"] for r in m]),
            "by_method": {k: sum(1 for r in m if r["match"] == k) for k in sorted({r["match"] for r in m})}}
m3 = {}
for kind in ("spec", "plan"):
    for arch in (False, True):
        m3[f"{kind}s_{'archived' if arch else 'top_level'}"] = m3_summary([r for r in sp_rows if r["kind"] == kind and r["archived"] == arch])
m3["all_top_level"] = m3_summary([r for r in sp_rows if not r["archived"]])

# ---------------------------------------------------------------- metrics 1 / 4: review coding
coded = {int(r["pr"]): r for r in csv.DictReader(open(os.path.join(DATA, "review-coding-manual.csv")))}
rev_rows = []
for n in pop:
    r = coded.get(n) or {"pr": str(n), "review_recorded": "none", "review_kind": "none", "pr_level_rounds": "0",
                         "first_round_blocking": "", "any_round_blocking_incl_per_task": "", "linked_record": "",
                         "linked_first_round_blocking": "", "basis": "No review of the PR's change recorded in the body"}
    r = dict(r); r["mergedAt"] = pr[n]["mergedAt"]; r["title"] = pr[n]["title"][:90]
    rev_rows.append(r)
reviewed = [r for r in rev_rows if r["review_recorded"] == "yes"]
def cnt(rows, key):
    out = {}
    for r in rows:
        out[r[key]] = out.get(r[key], 0) + 1
    return out
m1 = {"population": len(rev_rows), "review_recorded": cnt(rev_rows, "review_recorded"),
      "reviewed_first_round_blocking": cnt(reviewed, "first_round_blocking"),
      "reviewed_any_round_incl_per_task": cnt(reviewed, "any_round_blocking_incl_per_task"),
      "reviewed_body_plus_linked_record": cnt([dict(r, combo=(r["first_round_blocking"] if r["first_round_blocking"] != "ND" else (r["linked_first_round_blocking"] or "ND"))) for r in reviewed], "combo"),
      "by_kind": cnt(reviewed, "review_kind")}
_fr = m1["reviewed_first_round_blocking"]; _z, _b, _nd = _fr.get("0", 0), _fr.get("1+", 0), _fr.get("ND", 0)
m1["first_pass_determinable"] = {"zero": _z, "determinable": _z + _b, "rate": round(_z / (_z + _b), 3) if _z + _b else None,
                                 "lower_bound_all_reviewed": round(_z / len(reviewed), 3),
                                 "upper_bound_all_reviewed": round((_z + _nd) / len(reviewed), 3)}
by_type = {}
for r in rev_rows:
    t = "docs_only" if pr[int(r["pr"])]["docs_only"] else "code_touching"
    b = by_type.setdefault(t, {"prs": 0, "reviewed": 0, "0": 0, "1+": 0, "ND": 0})
    b["prs"] += 1
    if r["review_recorded"] == "yes":
        b["reviewed"] += 1; b[r["first_round_blocking"]] += 1
m1["by_pr_type"] = by_type

# numbered findings per reviewed PR (B0-R-3)
def ints(rows, key):
    return [int(r[key]) for r in rows if r.get(key, "").isdigit()]
m1["numbered_findings"] = {
    "from_id_ranges": quart(ints(reviewed, "findings_count_ids")), "from_id_ranges_n": len(ints(reviewed, "findings_count_ids")),
    "stated_counts_without_ids": quart(ints(reviewed, "findings_count_stated")),
    "id_or_stated": quart([int(r["findings_count_ids"]) if r["findings_count_ids"].isdigit() else int(r["findings_count_stated"])
                           for r in reviewed if r["findings_count_ids"].isdigit() or r["findings_count_stated"].isdigit()]),
    "first_round_blocking_count": quart(ints(reviewed, "first_round_blocking_count")),
    "first_round_blocking_count_hist": cnt([r for r in reviewed if r["first_round_blocking_count"].isdigit()], "first_round_blocking_count")}
rounds =[int(r["pr_level_rounds"]) for r in reviewed if r["pr_level_rounds"].isdigit()]
m4 = {"reviewed_prs": len(reviewed), "rounds_stated": len(rounds), "rounds_not_stated": len(reviewed) - len(rounds),
      "rounds": quart(rounds), "rounds_hist": {k: rounds.count(k) for k in sorted(set(rounds))},
      "prs_without_any_review_recorded": len(rev_rows) - len(reviewed)}
# by period: before and after REVIEW_PROTOCOL.md (added in 4ec1ae6, merged with PR #131)
t131 = pr[131]["t_merge"]
for label, sel in (("before_pr131", lambda r: ts(r["mergedAt"]) < t131), ("from_pr131", lambda r: ts(r["mergedAt"]) >= t131)):
    rows = [r for r in rev_rows if sel(r)]; rv = [r for r in rows if r["review_recorded"] == "yes"]
    rr = [int(r["pr_level_rounds"]) for r in rv if r["pr_level_rounds"].isdigit()]
    m1[label] = {"prs": len(rows), "reviewed": len(rv), "first_round_blocking": cnt(rv, "first_round_blocking"),
                 "findings_from_id_ranges": quart(ints(rv, "findings_count_ids"))}
    m4[label] = {"prs": len(rows), "reviewed": len(rv), "rounds_stated": len(rr), "rounds": quart(rr),
                 "rounds_hist": {k: rr.count(k) for k in sorted(set(rr))}}

# ---------------------------------------------------------------- write outputs
meta = {"head": head_full, "head_commit_time": iso(head_time), "population_rule": f"PRs merged at or after {WINDOW_START} and at or before HEAD's commit time",
        "population_size": len(pop), "population_range": [pop[0], pop[-1]],
        "all_merges_first_parent_ancestors": all(pr[n]["ancestor_of_head"] for n in pop),
        "merge_parent_counts": cnt([{"p": str(pr[n]["parents"])} for n in pop], "p"),
        "fix_subject_regex": FIX_RE.pattern, "fix_pr_title_regex": FIX_TITLE_RE.pattern}
json.dump({"meta": meta, "metric1_first_pass": m1, "metric2_rework": m2, "metric2_1014_proxy": proxy,
           "metric3_spec_to_delivery": m3, "metric4_interventions": m4, "metric5_size": m5,
           "metric5_definition_count": defs, "metric5_footprint": fp}, open(os.path.join(DATA, "summary.json"), "w"), indent=2, sort_keys=False)
json.dump(defs_lists, open(os.path.join(DATA, "definition-inventory.json"), "w"), indent=2)

def wcsv(name, rows):
    keys = []
    for r in rows:
        for k in r:
            if k not in keys and k != "body":
                keys.append(k)
    with open(os.path.join(DATA, name), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=keys, extrasaction="ignore"); w.writeheader(); w.writerows(rows)

wcsv("per-pr-size-and-fixes.csv", per_pr)
wcsv("spec-plan-matches.csv", sp_rows)
wcsv("footprint-per-skill.csv", fp_rows)
wcsv("review-coding-population.csv", rev_rows)
wcsv("fix-commits.csv", [{"sha": c["sha"][:12], "landing_pr": c["landing_pr"], "landed_at": iso(c["t_land"]),
                          "committed_at": iso(c["ct"]), "subject": c["subject"][:120], "n_files": len(c["files"])}
                         for c in sorted(fix_commits, key=lambda c: (c["t_land"], c["ct"]))])
print(json.dumps({"meta": meta, "m1": m1, "m4": m4, "proxy": proxy, "defs": defs}, indent=1))
