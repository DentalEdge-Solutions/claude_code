#!/usr/bin/env python3
"""Deterministic KPI snapshot from an ads project's audit_data/ dir. Stdlib-only.

Aggregates campaign_perf_30d.json (current-30d per-campaign metrics) into
account-level KPIs. Ratios are RECOMPUTED from summed totals (never averaged
across campaigns); impression_share is impression-weighted. Emits JSON.
"""
import argparse, hashlib, json, os, sys
from datetime import datetime, timezone

def _load(d, name):
    with open(os.path.join(d, name)) as f:
        return json.load(f)

def _num(x):
    try: return float(x)
    except (TypeError, ValueError): return 0.0

def _digits(x):
    return "".join(c for c in str(x) if c.isdigit())

class ProvenanceMismatch(Exception):
    """audit_data/ belongs to a different account than the one being labelled."""

def audit_data_customer_id(audit_data_dir):
    """Which account audit_data/ was actually collected for, per account.json."""
    rows = _load(audit_data_dir, "account.json")
    if isinstance(rows, dict):
        rows = [rows]
    for r in rows:
        cid = (r.get("customer") or {}).get("id")
        if cid:
            return _digits(cid)
    raise KeyError("account.json contains no customer.id — cannot verify provenance")

def assert_provenance(audit_data_dir, customer_id):
    """Refuse to label audit_data/ with an account it does not belong to.

    audit_data/ is ONE flat directory shared by every client: collecting for client B
    overwrites client A's files, and any dataset whose query failed keeps A's data
    while its neighbours refresh. Nothing downstream re-checks. Without this guard a
    snapshot taken after a failed or skipped collection is written into client B's
    vault carrying B's customer_id and A's numbers — not merely stale, but
    mislabelled cross-client data inside a per-client vault, which is exactly what
    the two-tier memory split exists to prevent.

    run-trend-audit.sh already clears stale REPORTS for this same reason; audit_data/
    had no equivalent. Comparison is by id, and only hashes are ever printed.
    """
    want = _digits(customer_id)
    got = audit_data_customer_id(audit_data_dir)
    if got != want:
        raise ProvenanceMismatch(
            "audit_data/ was collected for a DIFFERENT account than --customer.\n"
            f"  audit_data/account.json : sha12 {hashlib.sha1(got.encode()).hexdigest()[:12]}\n"
            f"  --customer              : sha12 {hashlib.sha1(want.encode()).hexdigest()[:12]}\n"
            "  Re-run collect-audit-data.sh for this client before snapshotting. "
            "Refusing rather than writing another client's numbers into this vault."
        )
    return got

def snapshot(audit_data_dir, customer_id, collected_at=None):
    assert_provenance(audit_data_dir, customer_id)   # fail closed BEFORE any labelling
    # campaign_perf_30d.json is the file the collector (audit_discovery.py) actually
    # refreshes and that audit_analyze reads for its 30-day numbers — so the snapshot
    # stays in lockstep with a fresh collection. (campaign_perf_cur30.json is written by
    # a different path and is NOT refreshed by collect-audit-data.sh — reading it yielded
    # stale KPIs; caught by the live gate.)
    perf = _load(audit_data_dir, "campaign_perf_30d.json")
    spend = conv = impr = clicks = 0.0
    is_num = is_den = 0.0
    for row in perf:
        m = row.get("metrics", {})
        spend += _num(m.get("costMicros")) / 1_000_000.0
        conv += _num(m.get("conversions"))
        i = _num(m.get("impressions")); impr += i
        clicks += _num(m.get("clicks"))
        sis = m.get("searchImpressionShare")
        if sis is not None:
            is_num += _num(sis) * i; is_den += i
    try:
        campaign_count = len(_load(audit_data_dir, "campaigns.json"))
    except FileNotFoundError:
        campaign_count = len(perf)
    def ratio(n, d): return round(n / d, 6) if d else 0.0
    return {
        "collected_at": collected_at or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "customer_id": str(customer_id),
        "spend": round(spend, 2),
        "conversions": round(conv, 2),
        "cost_per_conv": ratio(spend, conv),
        "ctr": ratio(clicks, impr),
        "conv_rate": ratio(conv, clicks),
        "impression_share": ratio(is_num, is_den),
        "impressions": int(impr),
        "clicks": int(clicks),
        "campaign_count": campaign_count,
    }

def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--audit-data", required=True)
    ap.add_argument("--customer", required=True)
    ap.add_argument("--collected-at")
    args = ap.parse_args(argv)
    try:
        snap = snapshot(args.audit_data, args.customer, args.collected_at)
    except ProvenanceMismatch as e:
        print(f"ads-metrics-snapshot: PROVENANCE REFUSED\n{e}", file=sys.stderr); return 2
    except (FileNotFoundError, json.JSONDecodeError, KeyError) as e:
        print(f"ads-metrics-snapshot: {e}", file=sys.stderr); return 2
    print(json.dumps(snap, indent=2)); return 0

if __name__ == "__main__":
    sys.exit(main())
