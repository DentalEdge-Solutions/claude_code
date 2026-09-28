#!/usr/bin/env python3
"""Security-review evidence helpers (spec 2026-09-28 §4-§5). Stdlib only.

Nothing here judges. It makes evidence safe to hand to a reviewer: slugs and customer ids
redacted, credentials reduced to fingerprints, and one canonical fingerprint hash.
"""
import hashlib, json, os, re

CLIENT = "<client>"
OBSERVED = "observed"
COULD_NOT_CHECK = "could-not-check"
SECRET_KEYS = ("GOOGLE_ADS_DEVELOPER_TOKEN", "GOOGLE_ADS_CLIENT_SECRET",
               "GOOGLE_ADS_REFRESH_TOKEN", "GOOGLE_ADS_CLIENT_ID")
ROLE_BY_NAME = {".env.ga": "read", ".env.gaw": "write"}
_MIN_SECRET_LEN = 8

# A value-shaped assignment, or Google's refresh-token prefix. `=//p'` (a sed we ran) and the
# rehearsal's placeholder are not values and must not count. Moved here from
# collect-review-evidence.py (final-review Group A) so both the collector and
# looks_like_credential_text share one definition.
CRED_TEXT_RE = re.compile(r"GOOGLE_ADS_(?:REFRESH_TOKEN|CLIENT_SECRET|DEVELOPER_TOKEN)="
                          r"(?!REHEARSAL-NOT-A-CREDENTIAL)[A-Za-z0-9_./-]{16,}|\b1//0[0-9A-Za-z_-]{20,}")
_CRED_KV_RE = re.compile(r"GOOGLE_ADS_[A-Z_]+=")


def looks_like_credential_text(text):
    """True if `text` looks like it holds (or tries to hold) a Google Ads credential
    assignment — used only to CLASSIFY a sweep hit the KEY=VALUE parser could not
    fingerprint (kind: unparsed), never to extract or print a value."""
    return bool(_CRED_KV_RE.search(text) or CRED_TEXT_RE.search(text))


def sha12(value):
    """sha1 of the bare value, first 12 hex — audit-credential-access.py:95's convention."""
    return hashlib.sha1(str(value).encode()).hexdigest()[:12]


def canon(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")


class Redactor:
    def __init__(self, slugs, customer_ids):
        self._slugs = sorted({s for s in slugs if s}, key=len, reverse=True)
        # Normalise to digits FIRST: a customer_id already stored dashed in
        # clients.json (e.g. "123-456-7890") must still redact both the dashed and
        # the plain-digit forms it can appear as elsewhere in evidence, not just its
        # own literal spelling (final-review Group E4).
        digits = set()
        for c in customer_ids:
            if not c:
                continue
            d = "".join(ch for ch in str(c) if ch.isdigit())
            if d:
                digits.add(d)
        self._cids = []
        for d in sorted(digits, key=len, reverse=True):
            self._cids.append((d, d))
            if len(d) == 10:
                self._cids.append((f"{d[:3]}-{d[3:6]}-{d[6:]}", d))

    @classmethod
    def from_clients_json(cls, path):
        """Raises ValueError if the registry cannot be read — the caller must then refuse to
        print anything, because it no longer knows what to hide."""
        try:
            with open(path, encoding="utf-8") as f:
                clients = json.load(f).get("clients", {})
        except (OSError, ValueError, AttributeError) as e:
            raise ValueError(f"cannot load the redaction list: {type(e).__name__}")
        if not isinstance(clients, dict):
            raise ValueError("cannot load the redaction list: 'clients' is not an object")
        return cls(list(clients), [(v or {}).get("customer_id", "") for v in clients.values()
                                   if isinstance(v, dict)])

    def text(self, s):
        for raw, digits in self._cids:
            s = s.replace(raw, "cid:" + sha12(digits))
        for slug in self._slugs:
            s = re.sub(rf"(?<![A-Za-z0-9]){re.escape(slug)}(?![A-Za-z0-9])", CLIENT, s)
        return s

    def obj(self, o):
        if isinstance(o, str):
            return self.text(o)
        if isinstance(o, dict):
            return {self.text(k) if isinstance(k, str) else k: self.obj(v) for k, v in o.items()}
        if isinstance(o, (list, tuple)):
            return [self.obj(v) for v in o]
        return o


def parse_credential_file(path):
    """(info, secrets). Values never leave this function except as sha12 fingerprints —
    `secrets` exists only so the caller can prove none reached its output."""
    values = {}
    with open(path, encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            if line.startswith("export "):
                line = line[len("export "):].lstrip()
            k, _, v = line.partition("=")
            k, v = k.strip(), v.strip()
            if len(v) >= 2 and v[0] == v[-1] and v[0] in "'\"":
                v = v[1:-1]
            values[k] = v
    role = values.get("GOOGLE_ADS_CREDENTIAL_ROLE") or ROLE_BY_NAME.get(os.path.basename(path), "unknown")
    rt, ci = values.get("GOOGLE_ADS_REFRESH_TOKEN", ""), values.get("GOOGLE_ADS_CLIENT_ID", "")
    info = {"path": path, "role": role,
            "refresh_token_sha12": sha12(rt) if rt else None,
            "client_id_sha12": sha12(ci) if ci else None}
    return info, [values[k] for k in SECRET_KEYS if values.get(k)]


def credential_set(infos):
    rows = [{"role": i["role"], "refresh_token_sha12": i["refresh_token_sha12"],
             "client_id_sha12": i["client_id_sha12"]} for i in infos]
    return sorted(rows, key=lambda r: canon(r))


def fingerprint(components):
    digests = {k: hashlib.sha256(canon(v)).hexdigest() for k, v in sorted(components.items())}
    complete = not any(isinstance(v, dict) and COULD_NOT_CHECK in v for v in components.values())
    return {"fingerprint": hashlib.sha256(canon(digests)).hexdigest(),
            "components": digests, "complete": complete}


def assert_no_secret(text, secrets):
    """The last line of defence: refuse to print if any credential value is present. Never
    says which one."""
    for s in secrets:
        if len(s) >= _MIN_SECRET_LEN and s in text:
            raise RuntimeError("output would contain a credential value — refusing to print")
