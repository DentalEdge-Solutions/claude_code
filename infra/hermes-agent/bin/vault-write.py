#!/usr/bin/env python3
"""Sole writer of per-client vault content. Stdlib-only. Writes ONLY under
<vault_root>/<slug>/ — every target is realpath-checked to be inside the vault."""
import argparse, json, os, re, shutil, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import vault_lib

TS_RE = re.compile(r"^\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2}$")

def _under(base, target):
    b = os.path.realpath(base); t = os.path.realpath(target)
    return t == b or t.startswith(b + os.sep)

def write(client, audit_file, metrics_file, ts, registry=None):
    if not TS_RE.fullmatch(ts or ""):
        raise ValueError(f"invalid --ts: {ts!r}")
    rec = vault_lib.resolve(client, registry)          # validates slug + customer_id
    vault = rec["vault_path"]
    audits, metrics = os.path.join(vault,"audits"), os.path.join(vault,"metrics")
    for d in (vault, audits, metrics):
        os.makedirs(d, exist_ok=True)
    audit_out = os.path.join(audits, f"{ts}-audit.md")
    metrics_out = os.path.join(metrics, f"{ts}.json")
    timeline = os.path.join(vault, "timeline.md")
    index = os.path.join(vault, "index.md")
    for tgt in (audit_out, metrics_out, timeline, index):
        if not _under(vault, tgt):
            raise ValueError(f"refusing write outside vault: {tgt}")
    shutil.copyfile(audit_file, audit_out)
    with open(metrics_file) as f: snap = json.load(f)
    with open(metrics_out, "w") as f: json.dump(snap, f, indent=2)
    if not os.path.exists(index):
        with open(index, "w") as f:
            f.write(f"# {client}\n\n- project: {rec.get('project','')}\n"
                    f"- customer_id: {rec.get('customer_id','')}\n"
                    f"- timezone: {rec.get('timezone','')}\n- currency: {rec.get('currency','')}\n")
    line = (f"- {ts} · audit · spend={snap.get('spend','?')} "
            f"conv={snap.get('conversions','?')} cpl={snap.get('cost_per_conv','?')}\n")
    with open(timeline, "a") as f: f.write(line)
    return {"audit": audit_out, "metrics": metrics_out}

def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--client", required=True)
    ap.add_argument("--audit-file", required=True)
    ap.add_argument("--metrics-file", required=True)
    ap.add_argument("--ts", required=True)
    ap.add_argument("--registry")
    args = ap.parse_args(argv)
    try:
        out = write(args.client, args.audit_file, args.metrics_file, args.ts, args.registry)
    except (ValueError, KeyError, FileNotFoundError) as e:
        print(f"vault-write: {e}", file=sys.stderr); return 2
    print(out["audit"]); return 0

if __name__ == "__main__":
    sys.exit(main())
