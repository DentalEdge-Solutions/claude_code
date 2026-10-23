#!/usr/bin/env python3
"""P1-01 follow-up computations on measure.py outputs (no git or GitHub calls).

Usage: python3 -I verify.py <data-dir>
1. Spec/plan matching: precision of the automatic rule against the hand verification, and the
   lead time recomputed with the corrected implementing PRs.
2. Fix attribution: lists every PR-level (fix PR -> earlier PR) pair attributed by any shared
   path within 7 days, and draws a seeded random sample of 20 pairs for hand checking.
3. Review coverage by PR type (docs-only vs code-touching).
4. Hand-validated post-merge fixes from fix-attribution-validation-manual.csv (fixes of the PR's own
   change, of which found after merge), and a check that every 10-14 proxy pair has a verdict.
Run after measure.py (reads summary.json).
"""
import csv, json, os, random, statistics, sys
from datetime import datetime, timezone

DATA = sys.argv[1]
DAY = 86400
ts = lambda s: datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc).timestamp()

prs = {p["number"]: p for p in json.load(open(os.path.join(DATA, "prs-merged-all.json")))}
rows = [r for r in csv.DictReader(open(os.path.join(DATA, "spec-plan-matches.csv"))) if r["archived"] == "False"]
manual = {r["file"]: r for r in csv.DictReader(open(os.path.join(DATA, "spec-plan-match-verification-manual.csv")))}

def q(xs):
    xs = sorted(xs)
    qq = statistics.quantiles(xs, n=4, method="inclusive")
    return {"n": len(xs), "min": xs[0], "p25": round(qq[0], 2), "median": round(qq[1], 2), "p75": round(qq[2], 2), "max": xs[-1]}

out = {"top_level_files": len(rows),
       "direct_to_main_before_pr_flow": sum(1 for r in rows if not r["landed_by_pr"]),
       "in_scope": sum(1 for r in rows if r["landed_by_pr"])}
matched = [r for r in rows if r.get("implementing_pr")]
verdict = {}
corrected_days, auto_days = [], []
for r in matched:
    base = os.path.basename(r["path"])
    m = manual.get(base, {"verdict": "correct", "corrected_pr": r["implementing_pr"]})
    verdict[m["verdict"]] = verdict.get(m["verdict"], 0) + 1
    auto_days.append(float(r["days"]))
    if m["verdict"] in ("correct", "partial", "wrong") and m["corrected_pr"]:
        t = ts(prs[int(m["corrected_pr"])]["mergedAt"]) - ts(r["first_commit_time"])
        corrected_days.append(round(t / DAY, 2))
out["matched_auto"] = len(matched)
out["unmatched_in_scope"] = [os.path.basename(r["path"]) for r in rows if r["landed_by_pr"] and not r.get("implementing_pr")]
out["manual_verdicts"] = verdict
out["auto_rule_precision_exact"] = round(verdict.get("correct", 0) / len(matched), 3)
out["auto_days"] = q(auto_days)
out["corrected_days"] = q(corrected_days)
for kind in ("spec", "plan"):
    ks = []
    for r in matched:
        if r["kind"] != kind:
            continue
        m = manual.get(os.path.basename(r["path"]), {"verdict": "correct", "corrected_pr": r["implementing_pr"]})
        if m["verdict"] in ("correct", "partial", "wrong") and m["corrected_pr"]:
            ks.append(round((ts(prs[int(m["corrected_pr"])]["mergedAt"]) - ts(r["first_commit_time"])) / DAY, 2))
    out[f"corrected_days_{kind}s"] = q(ks)

# ------------------------------------------------------------- fix attribution pairs
per = list(csv.DictReader(open(os.path.join(DATA, "per-pr-size-and-fixes.csv"))))
pairs = []
for r in per:
    if r["window7_complete"] != "True" or not r["fixpr_path_7d_ids"]:
        continue
    for y in r["fixpr_path_7d_ids"].split():
        pairs.append({"earlier_pr": int(r["pr"]), "earlier_title": prs[int(r["pr"])]["title"][:80],
                      "fix_pr": int(y), "fix_title": prs[int(y)]["title"][:80],
                      "days_after": round((ts(prs[int(y)]["mergedAt"]) - ts(prs[int(r["pr"])]["mergedAt"])) / DAY, 2)})
with open(os.path.join(DATA, "fixpr-path-7d-pairs.csv"), "w", newline="") as f:
    w = csv.DictWriter(f, fieldnames=list(pairs[0])); w.writeheader(); w.writerows(pairs)
rnd = random.Random(20261023)
sample = rnd.sample(pairs, 20)
with open(os.path.join(DATA, "fixpr-path-7d-sample20.csv"), "w", newline="") as f:
    w = csv.DictWriter(f, fieldnames=list(sample[0])); w.writeheader(); w.writerows(sample)
out["fixpr_path_7d_pairs"] = len(pairs)
json.dump(out, open(os.path.join(DATA, "verify-summary.json"), "w"), indent=2)
print(json.dumps(out, indent=1))
for s in sample:
    print(s["earlier_pr"], "|", s["earlier_title"][:60], "||", s["fix_pr"], "|", s["fix_title"][:70], "|", s["days_after"])

# ------------------------------------------------------------- review coverage by PR type
cod = {r["pr"]: r for r in csv.DictReader(open(os.path.join(DATA, "review-coding-population.csv")))}
by = {}
for r in per:
    t = "docs_only" if r["docs_only"] == "True" else "code_touching"
    c = cod[r["pr"]]
    b = by.setdefault(t, {"prs": 0, "review_recorded": 0, "first_round_0": 0, "first_round_1+": 0, "first_round_ND": 0})
    b["prs"] += 1
    if c["review_recorded"] == "yes":
        b["review_recorded"] += 1
        b["first_round_" + c["first_round_blocking"]] += 1
out2 = json.load(open(os.path.join(DATA, "verify-summary.json")))
out2["review_coverage_by_pr_type"] = by
json.dump(out2, open(os.path.join(DATA, "verify-summary.json"), "w"), indent=2)
print(json.dumps(by))

# ------------------------------------------------------------- hand-validated post-merge fixes (B0-R-5)
val = list(csv.DictReader(open(os.path.join(DATA, "fix-attribution-validation-manual.csv"))))
FIX = {"fix-known-at-merge", "fix-found-after-merge"}
def prs_with(setname, verdicts):
    return sorted({int(v["earlier_pr"]) for v in val if v["set"] == setname and v["verdict"] in verdicts})
hv = {}
for W, full in (("7d", sum(1 for r in per if r["window7_complete"] == "True")),
                ("30d", sum(1 for r in per if r["window30_complete"] == "True"))):
    s = "landref-" + W
    fixes = prs_with(s, FIX); esc = prs_with(s, {"fix-found-after-merge"})
    plaus = sorted(set(prs_with("path-sample-" + W, {"plausible-fix-found-after-merge"})) - set(fixes))
    hv[W] = {"complete_window_prs": full,
             "fixes_of_own_change": {"prs": fixes, "n": len(fixes), "share": round(len(fixes) / full, 3)},
             "with_plausible_unreferenced": {"prs": sorted(set(fixes) | set(plaus)), "n": len(set(fixes) | set(plaus)),
                                             "share": round(len(set(fixes) | set(plaus)) / full, 3)},
             "found_after_merge": {"prs": esc, "n": len(esc), "share": round(len(esc) / full, 3)},
             "found_after_merge_with_plausible": {"n": len(set(esc) | set(plaus)), "share": round(len(set(esc) | set(plaus)) / full, 3)}}
proxy_pairs = [v for v in val if v["set"] in ("landref-7d", "proxy-60d-only")]
summ = json.load(open(os.path.join(DATA, "summary.json")))["metric2_1014_proxy"]
landing = summ["landing_pr_to_referenced_prs"]
pairs = {(str(e), l) for l, es in landing.items() for e in es}
vmap = {(v["earlier_pr"], v["later_pr"]): v["verdict"] for v in proxy_pairs}
missing = sorted(p for p in pairs if p not in vmap)
hv["proxy_60d"] = {"landing_prs": len(landing), "pairs": len(pairs), "pairs_without_verdict": missing,
                   "fix_pairs": sum(1 for p in pairs if vmap.get(p) in FIX),
                   "found_after_merge_pairs": sum(1 for p in pairs if vmap.get(p) == "fix-found-after-merge")}
out3 = json.load(open(os.path.join(DATA, "verify-summary.json")))
out3["hand_validated_fixes"] = hv
json.dump(out3, open(os.path.join(DATA, "verify-summary.json"), "w"), indent=2)
print(json.dumps(hv))
