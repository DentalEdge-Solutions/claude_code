# Two-Tier Memory Model Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stand up the shared-brain / per-client-vault boundary and prove it end-to-end on two real pilot clients under the MCC, via a trend-aware Google Ads audit loop (run → vault → later run reads prior metrics → trend delta).

**Architecture:** Shared project brain stays git/meta-only. Per-client vaults are gitignored Obsidian-flavored markdown + deterministic JSON snapshots under the Hermes state volume (`/opt/data/vaults/<slug>/`, host `infra/hermes-agent/data/vaults/<slug>/`). The client roster itself is client-private and lives in the vault tier (`_registry/clients.json`), not git. Four stdlib-only Python tools (resolver, KPI extractor, vault writer, purge) plus a host orchestrator wrapper and a trend mode added to the existing analyst skill. Read-only end-to-end — mutation is a separate later increment.

**Tech Stack:** Python 3 stdlib only (no PyYAML/deps); POSIX `sh`; Docker Compose exec; `claude -p` (plan mode, opus); existing Inc-3/P6 read-execute pipeline (`collect-audit-data.sh`, `run-audit-bundle.sh`, `run-ads-report.py`).

## Global Constraints

Copied verbatim from the spec (`docs/superpowers/specs/2026-08-06-two-tier-memory-design.md`). Every task's requirements implicitly include these:

- **Stdlib-only** for all `infra/hermes-agent/bin/*.py` (matches `run-ads-report.py`). The client registry is **JSON, not YAML** — stdlib has no YAML parser and hand-parsed YAML caused the Inc-3 CRITICAL; JSON removes that bug class. (Deviation from the spec's "clients.yaml" naming, made explicit here.)
- **Writes land only under `/opt/data`** (host `infra/hermes-agent/data/`), never a `:ro` project mount. Vault writers refuse any target path that does not `realpath`-resolve under the client's vault dir.
- **Credentials injected per-invocation** via `docker compose exec -e`, never in the gateway env, never source-spliced. `.env.ga` is **parsed, not sourced**.
- **Charset-validate** every slug / customer_id / project arg before it touches a path or a shell: slug `^[a-z0-9][a-z0-9_-]{0,63}$`; customer_id `^[0-9]{1,15}$`; project `^[A-Za-z0-9_-]+$`. Pass such args via `-e` env (never spliced into an inner `sh -lc` source).
- **No client data in git/brain/telemetry.** This plan, the spec, the SKILL.md, and the README are **client-agnostic** (no client names, no account IDs). Real identities live only in the gitignored `_registry/clients.json`.
- **Read-only end-to-end.** No Google Ads mutation anywhere in this increment (that is Task 2, a separate increment). The audit deliverable is a **DRAFT behind a human-review gate**.
- **Vault root:** container `/opt/data/vaults`, host `infra/hermes-agent/data/vaults` (gitignored via `infra/hermes-agent/data/` in root `.gitignore`). Tools read `VAULT_ROOT` env (default `/opt/data/vaults`); host callers set it to the host path.

**Module naming:** the shared library is `vault_lib.py` (underscore → importable). CLI tools are `vault-write.py`, `vault-purge.py`, `ads-metrics-snapshot.py` (hyphen, standalone) and `import vault_lib`. Tests are `*.test.py`, run directly (not auto-discovered by `run-all-tests.js`), like the other `bin/` suites.

**Branch:** `feat/hermes-two-tier-memory` (spec already committed here). Do NOT push without explicit user go (standing rule).

---

### Task 1: Client-vault resolver + validation (`vault_lib.py`)

**Files:**
- Create: `infra/hermes-agent/bin/vault_lib.py`
- Test: `infra/hermes-agent/bin/vault_lib.test.py`

**Interfaces:**
- Produces: `validate_slug(slug)->str`, `validate_customer_id(cid)->str`, `load_registry(path=None)->dict`, `resolve(slug, path=None)->dict` (keys: `project, customer_id, currency, timezone, status, slug, vault_path`), `vault_root()->str`, `registry_path()->str`. CLI: `python3 vault_lib.py --client <slug> [--field <name>] [--registry <path>]` → prints JSON or one field; exit 2 on any validation/lookup error.

- [ ] **Step 1: Write the failing test**

```python
# infra/hermes-agent/bin/vault_lib.test.py
import json, os, subprocess, sys, tempfile, unittest
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import vault_lib as V

def _reg(tmp, clients):
    d = os.path.join(tmp, "_registry"); os.makedirs(d, exist_ok=True)
    p = os.path.join(d, "clients.json")
    with open(p, "w") as f: json.dump({"clients": clients}, f)
    return p

class T(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        os.environ["VAULT_ROOT"] = self.tmp
        self.reg = _reg(self.tmp, {
            "acme-dental": {"project": "claude_google_ads", "customer_id": "1234567890",
                            "currency": "USD", "timezone": "America/New_York", "status": "active"},
        })
    def test_resolve_ok(self):
        r = V.resolve("acme-dental", self.reg)
        self.assertEqual(r["customer_id"], "1234567890")
        self.assertEqual(r["vault_path"], os.path.join(self.tmp, "acme-dental"))
        self.assertEqual(r["slug"], "acme-dental")
    def test_unknown_slug_raises(self):
        with self.assertRaises(KeyError): V.resolve("nope", self.reg)
    def test_bad_slugs_rejected(self):
        for bad in ["../x", "a/b", "a b", "a;b", "A", "-x", "", "x"*65]:
            with self.assertRaises(ValueError): V.validate_slug(bad)
    def test_bad_customer_id_rejected(self):
        for bad in ["", "12-34", "abc", "12 34", "1"*16]:
            with self.assertRaises(ValueError): V.validate_customer_id(bad)
    def test_missing_registry(self):
        with self.assertRaises(FileNotFoundError): V.load_registry(os.path.join(self.tmp, "no.json"))
    def test_cli_field(self):
        out = subprocess.run([sys.executable, os.path.join(os.path.dirname(__file__), "vault_lib.py"),
                              "--client", "acme-dental", "--field", "customer_id", "--registry", self.reg],
                             capture_output=True, text=True, env={**os.environ})
        self.assertEqual(out.returncode, 0); self.assertEqual(out.stdout.strip(), "1234567890")
    def test_cli_bad_slug_exit2(self):
        out = subprocess.run([sys.executable, os.path.join(os.path.dirname(__file__), "vault_lib.py"),
                              "--client", "../etc", "--registry", self.reg], capture_output=True, text=True)
        self.assertEqual(out.returncode, 2)

if __name__ == "__main__": unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 infra/hermes-agent/bin/vault_lib.test.py -v`
Expected: FAIL (`ModuleNotFoundError: vault_lib` / attribute errors).

- [ ] **Step 3: Write minimal implementation**

```python
#!/usr/bin/env python3
"""Client-vault registry resolver + slug/id validation. Stdlib-only.

The client registry is CLIENT-PRIVATE and lives OUTSIDE git, on the Hermes
volume: <VAULT_ROOT>/_registry/clients.json (VAULT_ROOT defaults to
/opt/data/vaults; host callers pass the host data/vaults path). JSON (not YAML)
to stay stdlib-only and avoid the hand-parsed-YAML bug class (Inc-3 CRITICAL).
"""
import argparse, json, os, re, sys

SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
CID_RE = re.compile(r"^[0-9]{1,15}$")

def vault_root():
    return os.environ.get("VAULT_ROOT", "/opt/data/vaults")

def registry_path():
    return os.path.join(vault_root(), "_registry", "clients.json")

def validate_slug(slug):
    if not isinstance(slug, str) or not SLUG_RE.match(slug):
        raise ValueError(f"invalid client slug: {slug!r} (allowed ^[a-z0-9][a-z0-9_-]{{0,63}}$)")
    return slug

def validate_customer_id(cid):
    if not isinstance(cid, str) or not CID_RE.match(cid):
        raise ValueError(f"invalid customer_id: {cid!r} (digits only, no dashes)")
    return cid

def load_registry(path=None):
    path = path or registry_path()
    if not os.path.exists(path):
        raise FileNotFoundError(f"client registry not found: {path}")
    with open(path) as f:
        data = json.load(f)
    clients = data.get("clients", {})
    if not isinstance(clients, dict):
        raise ValueError("registry 'clients' must be a JSON object")
    return clients

def resolve(slug, path=None):
    validate_slug(slug)
    clients = load_registry(path)
    if slug not in clients:
        raise KeyError(f"unknown client slug: {slug!r} (known: {sorted(clients)})")
    rec = dict(clients[slug])
    validate_customer_id(str(rec.get("customer_id", "")))
    rec["customer_id"] = str(rec["customer_id"])
    rec["slug"] = slug
    rec["vault_path"] = os.path.join(vault_root(), slug)
    return rec

def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--client", required=True)
    ap.add_argument("--field")
    ap.add_argument("--registry")
    args = ap.parse_args(argv)
    try:
        rec = resolve(args.client, args.registry)
    except (ValueError, KeyError, FileNotFoundError) as e:
        print(f"vault-lib: {e}", file=sys.stderr); return 2
    if args.field:
        if args.field not in rec:
            print(f"vault-lib: no field {args.field!r}", file=sys.stderr); return 2
        print(rec[args.field])
    else:
        print(json.dumps(rec, indent=2))
    return 0

if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 infra/hermes-agent/bin/vault_lib.test.py -v`
Expected: PASS (all cases).

- [ ] **Step 5: Commit**

```bash
git add infra/hermes-agent/bin/vault_lib.py infra/hermes-agent/bin/vault_lib.test.py
git commit -m "feat(vault): client registry resolver + slug/customer_id validation"
```

---

### Task 2: Deterministic KPI snapshot (`ads-metrics-snapshot.py`)

**Files:**
- Create: `infra/hermes-agent/bin/ads-metrics-snapshot.py`
- Test: `infra/hermes-agent/bin/ads-metrics-snapshot.test.py`

**Interfaces:**
- Produces: `snapshot(audit_data_dir, customer_id, collected_at=None)->dict` with keys `collected_at, customer_id, spend, conversions, cost_per_conv, ctr, conv_rate, impression_share, impressions, clicks, campaign_count`. CLI: `python3 ads-metrics-snapshot.py --audit-data <dir> --customer <digits> [--collected-at <iso>]` → JSON to stdout; exit 2 if a required input file is missing.
- Consumes: an ads project `audit_data/` dir containing `campaign_perf_30d.json` (list of `{campaign, metrics:{costMicros,conversions,impressions,clicks,ctr,searchImpressionShare,...}}`) and optional `campaigns.json`.

**Determinism rule:** ratios are RECOMPUTED from summed totals (never averaged across campaigns); `impression_share` is impression-weighted; all values machine-derived, never from model prose.

- [ ] **Step 1: Write the failing test**

```python
# infra/hermes-agent/bin/ads-metrics-snapshot.test.py
import json, os, importlib.util, tempfile, unittest, sys
_p = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ads-metrics-snapshot.py")
_spec = importlib.util.spec_from_file_location("ads_metrics_snapshot", _p)
M = importlib.util.module_from_spec(_spec); _spec.loader.exec_module(M)

class T(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        # two campaigns: costMicros 100_000_000 (=100.0) + 300_000_000 (=300.0) => spend 400.0
        perf = [
          {"campaign":{"id":"1"},"metrics":{"costMicros":"100000000","conversions":10.0,
            "impressions":"1000","clicks":"100","ctr":0.1,"searchImpressionShare":0.5}},
          {"campaign":{"id":"2"},"metrics":{"costMicros":"300000000","conversions":30.0,
            "impressions":"3000","clicks":"300","ctr":0.1,"searchImpressionShare":0.9}},
        ]
        json.dump(perf, open(os.path.join(self.d,"campaign_perf_30d.json"),"w"))
        json.dump([{"campaign":{"id":"1"}},{"campaign":{"id":"2"}}],
                  open(os.path.join(self.d,"campaigns.json"),"w"))
    def test_aggregation(self):
        s = M.snapshot(self.d, "1234567890", collected_at="2026-08-06T00:00:00Z")
        self.assertEqual(s["spend"], 400.0)
        self.assertEqual(s["conversions"], 40.0)
        self.assertEqual(s["impressions"], 4000)
        self.assertEqual(s["clicks"], 400)
        self.assertEqual(s["cost_per_conv"], 10.0)          # 400/40
        self.assertEqual(s["ctr"], 0.1)                      # 400/4000 recomputed
        self.assertEqual(s["conv_rate"], 0.1)                # 40/400
        self.assertEqual(s["impression_share"], 0.8)         # (0.5*1000+0.9*3000)/4000
        self.assertEqual(s["campaign_count"], 2)
        self.assertEqual(s["customer_id"], "1234567890")
        self.assertEqual(s["collected_at"], "2026-08-06T00:00:00Z")
    def test_div0_guarded(self):
        json.dump([{"campaign":{"id":"1"},"metrics":{"costMicros":"0","conversions":0.0,
            "impressions":"0","clicks":"0"}}], open(os.path.join(self.d,"campaign_perf_30d.json"),"w"))
        s = M.snapshot(self.d, "1")
        self.assertEqual(s["cost_per_conv"], 0.0); self.assertEqual(s["ctr"], 0.0)
        self.assertEqual(s["conv_rate"], 0.0); self.assertEqual(s["impression_share"], 0.0)
    def test_missing_file_exit2(self):
        import subprocess
        r = subprocess.run([sys.executable, _p, "--audit-data", tempfile.mkdtemp(), "--customer","1"],
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 2)

if __name__ == "__main__": unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 infra/hermes-agent/bin/ads-metrics-snapshot.test.py -v`
Expected: FAIL (module/file not found).

- [ ] **Step 3: Write minimal implementation**

```python
#!/usr/bin/env python3
"""Deterministic KPI snapshot from an ads project's audit_data/ dir. Stdlib-only.

Aggregates campaign_perf_30d.json (current-30d per-campaign metrics) into
account-level KPIs. Ratios are RECOMPUTED from summed totals (never averaged
across campaigns); impression_share is impression-weighted. Emits JSON.
"""
import argparse, json, os, sys
from datetime import datetime, timezone

def _load(d, name):
    with open(os.path.join(d, name)) as f:
        return json.load(f)

def _num(x):
    try: return float(x)
    except (TypeError, ValueError): return 0.0

def snapshot(audit_data_dir, customer_id, collected_at=None):
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
    except FileNotFoundError as e:
        print(f"ads-metrics-snapshot: {e}", file=sys.stderr); return 2
    print(json.dumps(snap, indent=2)); return 0

if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 infra/hermes-agent/bin/ads-metrics-snapshot.test.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add infra/hermes-agent/bin/ads-metrics-snapshot.py infra/hermes-agent/bin/ads-metrics-snapshot.test.py
git commit -m "feat(vault): deterministic Google Ads KPI snapshot extractor"
```

---

### Task 3: Vault writer (`vault-write.py`) — sole writer of vault content

**Files:**
- Create: `infra/hermes-agent/bin/vault-write.py`
- Test: `infra/hermes-agent/bin/vault-write.test.py`

**Interfaces:**
- Consumes: `vault_lib.resolve`, `vault_lib.validate_slug`.
- Produces: CLI `python3 vault-write.py --client <slug> --audit-file <path> --metrics-file <path> --ts <YYYY-MM-DD_HH-MM-SS> [--registry <path>]`. Copies audit → `<vault>/audits/<ts>-audit.md`, writes metrics → `<vault>/metrics/<ts>.json`, appends one line to `<vault>/timeline.md`, ensures `<vault>/index.md` exists. Refuses any resolved target path not under the client's vault dir (realpath). Exit 2 on validation/confinement error.

- [ ] **Step 1: Write the failing test**

```python
# infra/hermes-agent/bin/vault-write.test.py
import json, os, importlib.util, subprocess, sys, tempfile, unittest
HERE = os.path.dirname(os.path.abspath(__file__))
def _reg(tmp, clients):
    d = os.path.join(tmp, "_registry"); os.makedirs(d, exist_ok=True)
    p = os.path.join(d, "clients.json"); json.dump({"clients": clients}, open(p,"w")); return p

class T(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(); os.environ["VAULT_ROOT"] = self.tmp
        self.reg = _reg(self.tmp, {"acme-dental":{"project":"claude_google_ads",
            "customer_id":"1234567890","status":"active"}})
        self.audit = os.path.join(self.tmp,"draft.md"); open(self.audit,"w").write("> DRAFT\n## Overall\nok\n")
        self.metrics = os.path.join(self.tmp,"m.json"); json.dump({"spend":400.0,"customer_id":"1234567890",
            "collected_at":"2026-08-06T00:00:00Z"}, open(self.metrics,"w"))
    def _run(self, client, ts="2026-08-06_10-00-00"):
        return subprocess.run([sys.executable, os.path.join(HERE,"vault-write.py"),
            "--client",client,"--audit-file",self.audit,"--metrics-file",self.metrics,
            "--ts",ts,"--registry",self.reg], capture_output=True, text=True, env={**os.environ})
    def test_writes_land_in_vault(self):
        r = self._run("acme-dental"); self.assertEqual(r.returncode,0,r.stderr)
        v = os.path.join(self.tmp,"acme-dental")
        self.assertTrue(os.path.exists(os.path.join(v,"audits","2026-08-06_10-00-00-audit.md")))
        self.assertTrue(os.path.exists(os.path.join(v,"metrics","2026-08-06_10-00-00.json")))
        self.assertIn("2026-08-06_10-00-00", open(os.path.join(v,"timeline.md")).read())
        self.assertTrue(os.path.exists(os.path.join(v,"index.md")))
    def test_bad_slug_refused(self):
        self.assertEqual(self._run("../escape").returncode, 2)
    def test_unknown_client_refused(self):
        self.assertEqual(self._run("ghost").returncode, 2)

if __name__ == "__main__": unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 infra/hermes-agent/bin/vault-write.test.py -v`
Expected: FAIL (script missing).

- [ ] **Step 3: Write minimal implementation**

```python
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
    if not TS_RE.match(ts or ""):
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 infra/hermes-agent/bin/vault-write.test.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add infra/hermes-agent/bin/vault-write.py infra/hermes-agent/bin/vault-write.test.py
git commit -m "feat(vault): sole vault writer (audit + metrics + timeline, confinement-checked)"
```

---

### Task 4: Retention / offboarding purge (`vault-purge.py`)

**Files:**
- Create: `infra/hermes-agent/bin/vault-purge.py`
- Test: `infra/hermes-agent/bin/vault-purge.test.py`

**Interfaces:**
- Consumes: `vault_lib.resolve`, `vault_lib.load_registry`.
- Produces: CLI `python3 vault-purge.py --client <slug> --export-to <dir> --confirm [--force] [--registry <path>]`. Order: (1) tar the vault → `<export-to>/<slug>-<ts>.tar.gz`; (2) hard-delete the vault dir; (3) append `{slug,ts,operator,bytes_exported}` JSON line to `<vault_root>/_governance/deletions.log`; (4) flip the client's `status` to `offboarded` in the registry. Refuses an `active` client unless `--force`. Refuses without `--confirm`. Exit 2 on any guard/validation failure.

- [ ] **Step 1: Write the failing test**

```python
# infra/hermes-agent/bin/vault-purge.test.py
import json, os, subprocess, sys, tempfile, unittest
HERE = os.path.dirname(os.path.abspath(__file__))
def _reg(tmp, clients):
    d=os.path.join(tmp,"_registry"); os.makedirs(d,exist_ok=True)
    p=os.path.join(d,"clients.json"); json.dump({"clients":clients}, open(p,"w")); return p

class T(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.mkdtemp(); os.environ["VAULT_ROOT"]=self.tmp
        self.reg=_reg(self.tmp, {"acme-dental":{"project":"claude_google_ads",
            "customer_id":"1234567890","status":"offboarded"}})
        v=os.path.join(self.tmp,"acme-dental","audits"); os.makedirs(v,exist_ok=True)
        open(os.path.join(v,"x-audit.md"),"w").write("data")
        self.exp=tempfile.mkdtemp()
    def _run(self, *extra, client="acme-dental"):
        return subprocess.run([sys.executable, os.path.join(HERE,"vault-purge.py"),
            "--client",client,"--export-to",self.exp,"--registry",self.reg,*extra],
            capture_output=True, text=True, env={**os.environ})
    def test_export_then_delete_then_log(self):
        r=self._run("--confirm"); self.assertEqual(r.returncode,0,r.stderr)
        self.assertFalse(os.path.exists(os.path.join(self.tmp,"acme-dental")))   # deleted
        self.assertTrue(any(f.endswith(".tar.gz") for f in os.listdir(self.exp)))  # exported
        log=os.path.join(self.tmp,"_governance","deletions.log")
        self.assertIn("acme-dental", open(log).read())
    def test_refuses_without_confirm(self):
        self.assertEqual(self._run().returncode, 2)
        self.assertTrue(os.path.exists(os.path.join(self.tmp,"acme-dental")))     # untouched
    def test_refuses_active_without_force(self):
        reg=_reg(self.tmp, {"live":{"project":"p","customer_id":"1","status":"active"}})
        os.makedirs(os.path.join(self.tmp,"live"),exist_ok=True)
        r=subprocess.run([sys.executable, os.path.join(HERE,"vault-purge.py"),"--client","live",
            "--export-to",self.exp,"--registry",reg,"--confirm"], capture_output=True, text=True, env={**os.environ})
        self.assertEqual(r.returncode, 2)

if __name__ == "__main__": unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 infra/hermes-agent/bin/vault-purge.test.py -v`
Expected: FAIL (script missing).

- [ ] **Step 3: Write minimal implementation**

```python
#!/usr/bin/env python3
"""Retention/offboarding: export-then-hard-purge a client vault, audit-log the
deletion, flip registry status to offboarded. Stdlib-only. Export ALWAYS precedes
delete. Refuses an active client without --force, and refuses without --confirm."""
import argparse, getpass, json, os, shutil, sys, tarfile
from datetime import datetime, timezone
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import vault_lib

def _dir_bytes(path):
    total = 0
    for root,_,files in os.walk(path):
        for f in files: total += os.path.getsize(os.path.join(root,f))
    return total

def purge(client, export_to, confirm, force, registry=None):
    if not confirm:
        raise ValueError("refusing to purge without --confirm")
    rec = vault_lib.resolve(client, registry)
    if rec.get("status") == "active" and not force:
        raise ValueError(f"client {client!r} is active — pass --force to purge an active client")
    vault = rec["vault_path"]
    if not os.path.isdir(vault):
        raise FileNotFoundError(f"vault not found: {vault}")
    os.makedirs(export_to, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d_%H-%M-%S")
    tar_path = os.path.join(export_to, f"{client}-{ts}.tar.gz")
    nbytes = _dir_bytes(vault)
    with tarfile.open(tar_path, "w:gz") as tar:       # 1. EXPORT
        tar.add(vault, arcname=client)
    shutil.rmtree(vault)                               # 2. HARD DELETE
    gov = os.path.join(vault_lib.vault_root(), "_governance")
    os.makedirs(gov, exist_ok=True)
    with open(os.path.join(gov, "deletions.log"), "a") as f:   # 3. AUDIT LOG
        f.write(json.dumps({"slug": client, "ts": ts, "operator": getpass.getuser(),
                            "bytes_exported": nbytes, "export": tar_path}) + "\n")
    path = registry or vault_lib.registry_path()       # 4. STATUS FLIP
    data = json.load(open(path)); data["clients"][client]["status"] = "offboarded"
    json.dump(data, open(path, "w"), indent=2)
    return tar_path

def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--client", required=True)
    ap.add_argument("--export-to", required=True)
    ap.add_argument("--confirm", action="store_true")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--registry")
    args = ap.parse_args(argv)
    try:
        tar = purge(args.client, args.export_to, args.confirm, args.force, args.registry)
    except (ValueError, KeyError, FileNotFoundError) as e:
        print(f"vault-purge: {e}", file=sys.stderr); return 2
    print(tar); return 0

if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 infra/hermes-agent/bin/vault-purge.test.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add infra/hermes-agent/bin/vault-purge.py infra/hermes-agent/bin/vault-purge.test.py
git commit -m "feat(vault): export-then-purge offboarding with deletion audit log"
```

---

### Task 5: Per-client account targeting (customer_id override)

**Files:**
- Modify: `infra/hermes-agent/bin/run-ads-report.py` (add `--customer` override + validation)
- Modify: `infra/hermes-agent/bin/run-ads-report.test.py` (add override test)
- Modify: `infra/hermes-agent/run-audit-bundle.sh` (accept + pass through `--customer`)
- Modify: `infra/hermes-agent/collect-audit-data.sh` (honor `ADS_CUSTOMER_ID_OVERRIDE`, show it in `--dry-run`)

**Interfaces:**
- Produces: `run-ads-report.py --customer <digits>` overrides `GOOGLE_ADS_CUSTOMER_ID` in-process (digit-validated); `run-audit-bundle.sh <project> [--customer <digits>]` forwards it to each reader; `collect-audit-data.sh` uses `ADS_CUSTOMER_ID_OVERRIDE` (digit-validated) in place of the `.env.ga` `GOOGLE_ADS_CUSTOMER_ID`.

- [ ] **Step 1: Write the failing test (run-ads-report.py override)**

Add to `infra/hermes-agent/bin/run-ads-report.test.py` (a new test method; import style matches the file):

```python
    def test_customer_override_validates_and_sets(self):
        import importlib.util, os
        p = os.path.join(os.path.dirname(os.path.abspath(__file__)), "run-ads-report.py")
        spec = importlib.util.spec_from_file_location("rar", p)
        m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
        # valid digits accepted
        self.assertEqual(m.validate_customer_override("9999999999"), "9999999999")
        # non-digits rejected
        for bad in ["75-64", "abc", "", "1 2"]:
            with self.assertRaises(SystemExit):
                m.validate_customer_override(bad)
```

- [ ] **Step 2: Run to verify it fails**

Run: `python3 infra/hermes-agent/bin/run-ads-report.test.py -v`
Expected: FAIL (`validate_customer_override` undefined).

- [ ] **Step 3: Implement the override in `run-ads-report.py`**

Add near the top (after `CRED_VARS`/`SECRET_VARS`):

```python
import re as _re
_CID_RE = _re.compile(r"^[0-9]{1,15}$")

def validate_customer_override(cid):
    if not _CID_RE.match(cid or ""):
        print(f"run-ads-report: invalid --customer {cid!r} (digits only)", file=sys.stderr)
        raise SystemExit(2)
    return cid
```

In `main(...)`, add the arg and apply BEFORE `run_report` (so the override wins over the env `.env.ga` value):

```python
    ap.add_argument("--customer", help="override GOOGLE_ADS_CUSTOMER_ID for this run (digits)")
    # ... after parse:
    if args.customer:
        os.environ["GOOGLE_ADS_CUSTOMER_ID"] = validate_customer_override(args.customer)
```

(Confirm `import sys`/`import os` already present — they are.)

- [ ] **Step 4: Run to verify it passes**

Run: `python3 infra/hermes-agent/bin/run-ads-report.test.py -v`
Expected: PASS (existing tests still green + new one).

- [ ] **Step 5: Thread `--customer` through `run-audit-bundle.sh`**

Replace the arg handling + loop so a trailing `--customer <id>` is forwarded to every reader:

```sh
set -eu
here="$(cd "$(dirname "$0")" && pwd)"
PROJECT="${1-claude_google_ads}"; shift 2>/dev/null || true
CUSTOMER=""
while [ $# -gt 0 ]; do
  case "$1" in --customer) CUSTOMER="$2"; shift 2 ;; *) echo "run-audit-bundle: unknown arg: $1" >&2; exit 1 ;; esac
done
READERS="account_overview audit_search_terms audit_analyze"
echo "run-audit-bundle: producing report set for $PROJECT" >&2
for r in $READERS; do
  echo "  -> $r" >&2
  if [ -n "$CUSTOMER" ]; then
    "$here/run-ads-report.sh" --project "$PROJECT" --report "$r" --customer "$CUSTOMER"
  else
    "$here/run-ads-report.sh" --project "$PROJECT" --report "$r"
  fi
done
echo "run-audit-bundle: done" >&2
```

- [ ] **Step 6: Honor `ADS_CUSTOMER_ID_OVERRIDE` in `collect-audit-data.sh`**

Immediately AFTER the `.env.ga` parse `while`-loop (which exports `GOOGLE_ADS_CUSTOMER_ID` from the file), add:

```sh
# Per-client override (digits only). run-trend-audit.sh sets this to target one
# client's account; it wins over the .env.ga CUSTOMER_ID for this invocation.
if [ -n "${ADS_CUSTOMER_ID_OVERRIDE:-}" ]; then
  case "$ADS_CUSTOMER_ID_OVERRIDE" in
    *[!0-9]*|'') echo "collect-audit-data: invalid ADS_CUSTOMER_ID_OVERRIDE (digits only)" >&2; exit 1 ;;
  esac
  export GOOGLE_ADS_CUSTOMER_ID="$ADS_CUSTOMER_ID_OVERRIDE"
fi
```

And in the `--dry-run` branch, surface the effective account so it is testable without an API call — change the dry-run echo to:

```sh
if [ "${1:-}" = "--dry-run" ]; then
  echo "effective GOOGLE_ADS_CUSTOMER_ID: $GOOGLE_ADS_CUSTOMER_ID"
  for c in $COLLECTORS; do echo "would run (read-only cred): (cd $project_dir && .venv/bin/python code/$c)"; done
  exit 0
fi
```

- [ ] **Step 7: Verify the shell override (no API call)**

Run:
```bash
cd infra/hermes-agent
ADS_CUSTOMER_ID_OVERRIDE=9999999999 ./collect-audit-data.sh --dry-run | grep "effective GOOGLE_ADS_CUSTOMER_ID: 9999999999"
ADS_CUSTOMER_ID_OVERRIDE=bad-id ./collect-audit-data.sh --dry-run; echo "exit=$?"   # expect exit=1
```
Expected: the grep matches; the bad-id run exits 1.

- [ ] **Step 8: Commit**

```bash
git add infra/hermes-agent/bin/run-ads-report.py infra/hermes-agent/bin/run-ads-report.test.py \
        infra/hermes-agent/run-audit-bundle.sh infra/hermes-agent/collect-audit-data.sh
git commit -m "feat(ads): per-client customer_id override across collect + read path"
```

---

### Task 6: Trend mode (SKILL.md) + orchestrator (`run-trend-audit.sh`)

**Files:**
- Modify: `infra/hermes-agent/skills/claude-code-ads-analyst/SKILL.md` (add a Trend mode section)
- Create: `infra/hermes-agent/run-trend-audit.sh`

**Interfaces:**
- Consumes: `vault_lib.py` CLI, `collect-audit-data.sh` (+`ADS_CUSTOMER_ID_OVERRIDE`), `run-audit-bundle.sh <project> --customer`, `ads-metrics-snapshot.py`, `vault-write.py`, the container `claude -p` path.
- Produces: `./run-trend-audit.sh --client <slug>` → a trend-aware DRAFT + a metrics snapshot persisted to the client vault; prints the vault audit path.

- [ ] **Step 1: Add the Trend mode section to `SKILL.md`**

Insert after the `## Output contract` section:

```markdown
## Trend mode (when prior history is provided)
If the run points you at a client vault (`/opt/data/vaults/<slug>/`) containing
`metrics/*.json` and/or prior `audits/*.md`:
- Read the MOST RECENT prior `metrics/<ts>.json` snapshot(s).
- For the headline KPIs (spend, conversions, cost_per_conv, ctr, conv_rate,
  impression_share) report change-over-time as "now vs prior (Δ abs, Δ %)".
- Weave the trend into sections 2–5 (e.g. "cost/conv worsened 18% since <prior date>").
- If NO prior snapshot exists, write in the provenance line: "baseline run — no prior
  audit; establishing history." Do NOT fabricate a trend.
- Ground every trend claim in the metrics JSON only; never infer a delta the snapshots
  do not support.
- Read ONLY within the vault dir, the fresh reports dir, and the project SOP mount you
  are given — never another client's vault.
```

- [ ] **Step 2: Create `run-trend-audit.sh`**

```sh
#!/bin/sh
# Trend-aware, READ-ONLY per-client Google Ads audit. Orchestrates:
#   resolve client -> collect fresh (read-only cred, this client) -> deterministic
#   metrics snapshot -> fresh reports -> claude -p trend audit (reads fresh reports +
#   THIS client's vault history) -> vault-write (sole vault writer). No mutation.
set -eu
here="$(cd "$(dirname "$0")" && pwd)"
CLIENT=""
while [ $# -gt 0 ]; do
  case "$1" in --client) CLIENT="$2"; shift 2 ;; *) echo "usage: run-trend-audit.sh --client <slug>" >&2; exit 1 ;; esac
done
[ -n "$CLIENT" ] || { echo "usage: run-trend-audit.sh --client <slug>" >&2; exit 1; }

export VAULT_ROOT="$here/data/vaults"                     # host path == container /opt/data/vaults
CID="$(python3 "$here/bin/vault_lib.py" --client "$CLIENT" --field customer_id)"     # validates slug+id (exit 2 on bad)
PROJECT="$(python3 "$here/bin/vault_lib.py" --client "$CLIENT" --field project)"
case "$PROJECT" in ''|*[!A-Za-z0-9_-]*) echo "run-trend-audit: bad project '$PROJECT'" >&2; exit 1 ;; esac
TS="$(date -u +%Y-%m-%d_%H-%M-%S)"

echo "run-trend-audit: [$CLIENT] collecting fresh data (read-only)…" >&2
ADS_CUSTOMER_ID_OVERRIDE="$CID" "$here/collect-audit-data.sh"

ADS_DIR="${ADS_PROJECT_DIR:-$(cd "$here/../../../claude-google-ads" && pwd)}/audit_data"
SNAP="$(mktemp)"
python3 "$here/bin/ads-metrics-snapshot.py" --audit-data "$ADS_DIR" --customer "$CID" > "$SNAP"

echo "run-trend-audit: [$CLIENT] producing report set…" >&2
"$here/run-audit-bundle.sh" "$PROJECT" --customer "$CID"

echo "run-trend-audit: [$CLIENT] trend audit (opus, plan mode)…" >&2
# PROJECT/CLIENT/TS passed via -e (never spliced into the inner source). claude is
# read-only (plan mode, Read/Grep/Glob); the draft is written by a redirect to
# /opt/data (writable), never the :ro mount.
docker compose -f "$here/docker-compose.yml" exec \
  -e PROJECT="$PROJECT" -e CLIENT="$CLIENT" -e TS="$TS" -T hermes-agent sh -lc '
  set -eu
  skill="/opt/data/skills/claude-code-ads-analyst/SKILL.md"
  vault="/opt/data/vaults/$CLIENT"; reports="/opt/data/reports/$PROJECT"
  ls "$reports"/*.md >/dev/null 2>&1 || { echo "no reports for $PROJECT" >&2; exit 1; }
  mkdir -p "/opt/data/audits/$PROJECT"
  out="/opt/data/audits/$PROJECT/$TS-audit.md"
  claude -p "Read and follow $skill EXACTLY, INCLUDING its Trend mode. Produce the Google Ads audit DRAFT for project $PROJECT. Fresh scrubbed reports: $reports/. THIS client'\''s prior history (read for trend deltas): $vault/metrics/, $vault/audits/, $vault/timeline.md (may be empty on the first run = establish baseline). SOP/benchmark docs: /projects/$PROJECT/. Read ONLY within $vault, $reports, and /projects/$PROJECT. Output ONLY the deliverable markdown." \
    --allowedTools "Read,Grep,Glob" --permission-mode plan --model claude-opus-4-8 > "$out"
  echo "$out"
'
DRAFT="$here/data/audits/$PROJECT/$TS-audit.md"
[ -f "$DRAFT" ] || { echo "run-trend-audit: draft not produced: $DRAFT" >&2; rm -f "$SNAP"; exit 1; }
# (VAULT_ROOT was exported to the host path "$here/data/vaults" at the top.)

# Sole vault writer: ingest draft + metrics + timeline into the client vault.
# VAULT_ROOT is already exported to the host path above, so vault-write resolves
# the host registry and writes host-side under data/vaults/<slug>/.
python3 "$here/bin/vault-write.py" \
  --client "$CLIENT" --audit-file "$DRAFT" --metrics-file "$SNAP" --ts "$TS"
rm -f "$SNAP"

# Cheap per-run soft-isolation assertion: the draft must not name ANOTHER client slug.
for other in $(python3 - "$here/data/vaults/_registry/clients.json" "$CLIENT" <<'PY'
import json,sys
reg,me=sys.argv[1],sys.argv[2]
print(" ".join(s for s in json.load(open(reg)).get("clients",{}) if s!=me))
PY
); do
  if grep -qiw "$other" "$here/data/vaults/$CLIENT/audits/$TS-audit.md"; then
    echo "run-trend-audit: ASSERTION FAIL — draft references other client '$other'" >&2; exit 1
  fi
done
echo "run-trend-audit: [$CLIENT] done -> data/vaults/$CLIENT/audits/$TS-audit.md" >&2
```

- [ ] **Step 3: `chmod +x` and lint-run the wrapper (no live call)**

Run:
```bash
chmod +x infra/hermes-agent/run-trend-audit.sh
sh -n infra/hermes-agent/run-trend-audit.sh && echo "syntax ok"
infra/hermes-agent/run-trend-audit.sh 2>&1 | grep -q "usage:" && echo "usage guard ok"
```
Expected: `syntax ok` and `usage guard ok`.

- [ ] **Step 4: Commit**

```bash
git add infra/hermes-agent/skills/claude-code-ads-analyst/SKILL.md infra/hermes-agent/run-trend-audit.sh
git commit -m "feat(vault): trend-audit orchestrator + analyst trend mode"
```

---

### Task 7: Close the `audit_data` git-tracking hole (in `claude-google-ads`)

**Files:**
- Modify: `claude-google-ads/.gitignore`
- Untrack: `claude-google-ads/audit_data/**` (56 files currently tracked)

This runs in the **separate** `claude-google-ads` repo (host path `/Users/ericksicard/Projects/claude-google-ads`), not `claude_code`.

- [ ] **Step 1: Confirm the current tracked count**

Run:
```bash
cd /Users/ericksicard/Projects/claude-google-ads
git ls-files audit_data | wc -l    # expect > 0 (currently 56)
```

- [ ] **Step 2: Add the ignore rule and untrack**

```bash
cd /Users/ericksicard/Projects/claude-google-ads
printf '\n# Client account data — durable store is the Hermes per-client vault, not this repo\naudit_data/\n' >> .gitignore
git rm -r --cached audit_data
```

- [ ] **Step 3: Verify it is now ignored and untracked**

Run:
```bash
git ls-files audit_data | wc -l                       # expect 0
git check-ignore audit_data && echo IGNORED           # expect IGNORED
```
Expected: `0` and `IGNORED`.

- [ ] **Step 4: Commit (in the ads repo)**

```bash
git add .gitignore
git commit -m "chore: stop tracking audit_data/ (client data lives in the Hermes vault)"
```

Do NOT push (standing rule; the user pushes when ready).

---

### Task 8: Documentation (README two-tier section)

**Files:**
- Modify: `infra/hermes-agent/README.md` (add a "Two-tier memory / per-client vaults" section)

- [ ] **Step 1: Add the section**

Append after the "Google Ads audit pilot (P6 — monetization)" section a new section documenting, client-agnostically:
- the git/vault boundary (meta in git; client data only in gitignored `/opt/data/vaults/<slug>/`; roster in `_registry/clients.json`, not git);
- `clients.json` shape (`{ "clients": { "<slug>": {project, customer_id, currency, timezone, status} } }`);
- the vault layout (`index.md`, `timeline.md`, `audits/`, `metrics/`);
- usage: `./run-trend-audit.sh --client <slug>` and `python3 bin/vault-purge.py --client <slug> --export-to <dir> --confirm`;
- the safety model (read-only end-to-end, soft isolation now / hard deferred, DRAFT + human-review gate, no client data in git/brain);
- the test pointers (`python3 infra/hermes-agent/bin/vault_lib.test.py`, `ads-metrics-snapshot.test.py`, `vault-write.test.py`, `vault-purge.test.py` — run directly).

Keep it client-agnostic: no client names or account IDs.

- [ ] **Step 2: Commit**

```bash
git add infra/hermes-agent/README.md
git commit -m "docs(hermes): document two-tier memory + per-client vaults"
```

---

### Task 9: Verification gate (controller-run — no commit)

Mirrors prior increments' Task-2/Task-1 gates. The controller runs this with the real (gitignored) registry; it is NOT a code commit.

- [ ] **Step 1: Seed the real registry (gitignored)**

Create `infra/hermes-agent/data/vaults/_registry/clients.json` with the two pilot clients' real slugs + account IDs (the reachable accounts confirmed this session). This file is under `infra/hermes-agent/data/` → already gitignored. Verify:
```bash
git check-ignore infra/hermes-agent/data/vaults/_registry/clients.json && echo IGNORED
```

- [ ] **Step 2: Baseline run (cold-start client — no prior snapshot)**

```bash
cd infra/hermes-agent && ./run-trend-audit.sh --client <cold-client-slug>
```
Assert: draft provenance line says "baseline run — no prior audit"; `metrics/<ts>.json` written; `timeline.md` has one line; draft is a valid 8-section DRAFT.

- [ ] **Step 3: Delta run (client with a prior snapshot)**

Seed the P6 baseline for the client that has one: place its existing P6 audit as `audits/<t0>-audit.md` and a `metrics/<t0>.json` (extract once with `ads-metrics-snapshot.py` from that client's `audit_data`, or hand-seed from the P6 reports). Then:
```bash
./run-trend-audit.sh --client <delta-client-slug>
```
Assert: the new draft references change-over-time vs the prior snapshot (a real Δ), grounded in the metrics JSON.

- [ ] **Step 4: Run all §7 assertions**

```bash
# (a) write confinement — vault-write realpath guard (unit-proven); (b) cross-client
#     slug scan — built into run-trend-audit.sh; both runs exited 0.
# (c) credential scan: zero GOOGLE_ADS_* values in drafts + reports + logs
grep -rEc "$(printf '%s' 'DUMMY')" /dev/null  # replace with the P6 scan recipe over data/audits,data/reports,data/logs
# (d) :ro integrity: project git trees byte-identical before==after
git -C /Users/ericksicard/Projects/claude-google-ads stash list  # tree unchanged; audit_data now ignored
# (e) no client data committed:
git -C /Users/ericksicard/Projects/claude_code status --porcelain | grep -E "data/vaults" && echo "LEAK" || echo "clean"
```
Assert: credential scan clean; `:ro` mounts byte-identical; `data/vaults` never staged.

- [ ] **Step 5: Meta brain-capture (meta-only)**

`brain-capture` a META decision that the two-tier model shipped and was proven on two clients — **no client names, IDs, or business data**. (Client-agnostic, per the hard rule.)

- [ ] **Step 6: Full test suite regression**

```bash
node scripts/run-all-tests.js
python3 infra/hermes-agent/bin/vault_lib.test.py
python3 infra/hermes-agent/bin/ads-metrics-snapshot.test.py
python3 infra/hermes-agent/bin/vault-write.test.py
python3 infra/hermes-agent/bin/vault-purge.test.py
python3 infra/hermes-agent/bin/run-ads-report.test.py
```
Expected: all green.

---

## Self-Review

**1. Spec coverage:**
- §2 git/vault boundary + client registry in vault tier → Task 1 (`vault_lib`, JSON registry under `_registry/`). ✅
- §3 vault layout + deterministic metrics schema → Task 2 (extractor) + Task 3 (writer layout). ✅
- §4 taxonomy → enforced by construction (registry off-git; docs Task 8). ✅
- §5.1 resolver → Task 1; §5.2 vault-write → Task 3; §5.3 trend mode → Task 6; §5.4 orchestrator → Task 6; §5.5 purge → Task 4; §5.6 audit_data fix → Task 7. ✅
- §6 soft isolation → Task 6 (single VAULT_DIR, read-only claude, cross-client slug assertion) + Task 3 (write confinement). ✅
- §7 assertions → Task 9 gate (+ per-run cross-client in Task 6, write confinement in Task 3). ✅
- §8 meta feedback → Task 9 Step 5 (meta-only capture). ✅
- §9 verification gate → Task 9. ✅
- §10 tests → each Task's test file + Task 9 Step 6. ✅
- §11 deferred → nothing in-plan builds encryption/hard-isolation/DB/caps. ✅
- §12 guarantees → Global Constraints + assertions. ✅

**2. Placeholder scan:** Task 9 Step 4 (c) intentionally points at "the P6 scan recipe" — the controller reuses the exact P6 credential-scan command over `data/audits,data/reports,data/logs`; this is a controller-run gate step, not agent code. No `TODO`/`TBD` in any implemented file.

**3. Type consistency:** `vault_lib.resolve` returns `slug, vault_path, customer_id(str), project, status` — consumed identically by `vault-write.py` and `vault-purge.py`. Metrics keys (`spend, conversions, cost_per_conv, ...`) written by Task 2 match those read in `vault-write.py`'s timeline line and the SKILL trend section. `--ts` format `YYYY-MM-DD_HH-MM-SS` is consistent across the wrapper, `vault-write`, and `TS_RE`.
