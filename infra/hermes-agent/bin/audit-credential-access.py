"""Measure what a Google Ads credential can ACTUALLY do, and compare it to what it
is DECLARED to do.

WHY THIS EXISTS
    Every access-level guarantee in this repo has been an assertion in prose:
    ".env.ga is read-only", ".env.gaw is Standard-access". Twice those assertions
    were wrong, and both times the discrepancy surfaced only by luck. Prose cannot
    be checked; this can.

    CREDENTIAL-scoped, not project-scoped. It takes an injected credential and asks
    Google what that credential can do, so it works unchanged for the project
    replacing claude-google-ads and for every project after it.

STRUCTURALLY NON-MUTATING
    The mutate probe hardcodes validate_only=True. There is no flag to disable it.
    Every other probe is a SELECT. This script cannot change an account.

WHAT IT MEASURES
    read    — can it read the target account? Positive control for everything else:
              without a successful read, a refusal below proves nothing about
              access level (it could be a bad token).
    scope   — how many accounts are reachable under the login customer. This is the
              blast radius, and it is the number that matters once Hermes holds
              credentials for more than one project.
    mutate  — validate_only mutate against a SEARCH campaign. Three-valued:
              PERMITTED / DENIED (authorization) / INCONCLUSIVE (anything else).
              A SEARCH campaign is required because campaign-level negative
              keywords are not valid on every channel type, and a context refusal
              is not an authorization refusal.
    roles   — the access_role table from customer_user_access, for the MCC and for
              the target account. This is Google's own ground truth about who holds
              what, and it is the only non-behavioural evidence available here.

    manager_admin — is the credential ADMIN at the MANAGER level? validate_only
              update of the manager account's own descriptive_name, set to the value
              it already holds. Touches no client ad account.

A NOTE ON HOW THIS PROBE WAS ARRIVED AT
    Two earlier attempts were wrong, and both failed in the confident direction:

      1. Reading customer_user_access was treated as proof of ADMIN. It is not a
         discriminator at all — a READ_ONLY credential reads it successfully. The
         tool reported ADMIN for a credential whose mutate was refused in the SAME
         run, an internal contradiction it should have caught itself.
      2. This file then claimed admin was not measurable, reasoning that
         MutateCustomerUserAccessRequest has no validate_only. True, but the wrong
         service: MutateCustomerRequest HAS validate_only, and updating the manager
         account is admin-gated.

    The current probe is verified DISCRIMINATING against a known-READ_ONLY control,
    which is the check both earlier versions lacked. A probe that has not been shown
    to refuse a credential that should be refused proves nothing when it accepts one.

VERDICT LADDER
    UNUSABLE      — cannot even read
    READ_ONLY     — reads, mutate refused with an authorization error
    MUTATE_CAPABLE— reads, validate_only mutate accepted
    INCONCLUSIVE  — reads, but the mutate probe could not reach an authorization
                    decision (say so; never round it to a verdict)

Exit 0 = declared and measured agree · 2 = unusable · 3 = MISMATCH · 4 = inconclusive.

Credentials come strictly from the injected environment — never a local .env, which
would silently pick up a project's own full-access token. No credential value is
ever printed.
"""

import hashlib
import json
import os
import sys

try:                                    # the SDK lives in the pinned /opt/ads-venv.
    from google.ads.googleads.client import GoogleAdsClient
    from google.ads.googleads.errors import GoogleAdsException
    SDK = True
except ImportError:                     # host-side: the pure classification logic
    GoogleAdsClient = None              # is still importable and unit-testable.
    class GoogleAdsException(Exception):
        pass
    SDK = False

API_VERSION = "v24"
REQUIRED = ("GOOGLE_ADS_DEVELOPER_TOKEN", "GOOGLE_ADS_CLIENT_ID",
            "GOOGLE_ADS_CLIENT_SECRET", "GOOGLE_ADS_REFRESH_TOKEN",
            "GOOGLE_ADS_LOGIN_CUSTOMER_ID", "GOOGLE_ADS_CUSTOMER_ID")

ACCESS_ROLE = {0: "UNSPECIFIED", 1: "UNKNOWN", 2: "ADMIN",
               3: "STANDARD", 4: "READ_ONLY", 5: "EMAIL_ONLY"}

# Error codes that mean "the platform refused this on authorization grounds".
AUTH_DENIED = ("ACTION_NOT_PERMITTED", "USER_PERMISSION_DENIED",
               "NOT_ADS_USER", "CUSTOMER_NOT_ENABLED")


def sha12(v):
    return hashlib.sha1(str(v).encode()).hexdigest()[:12]


def digits(v, field):
    d = str(v).replace("-", "").replace(" ", "")
    if not d.isdigit() or not 1 <= len(d) <= 15:
        raise ValueError(f"invalid {field}")
    return d


def build_client(env):
    missing = [k for k in REQUIRED if not env.get(k)]
    if missing:
        raise ValueError(f"missing injected credential vars: {', '.join(missing)} "
                         "(this script never falls back to an in-tree .env)")
    cfg = {"developer_token": env["GOOGLE_ADS_DEVELOPER_TOKEN"],
           "client_id": env["GOOGLE_ADS_CLIENT_ID"],
           "client_secret": env["GOOGLE_ADS_CLIENT_SECRET"],
           "refresh_token": env["GOOGLE_ADS_REFRESH_TOKEN"],
           "login_customer_id": digits(env["GOOGLE_ADS_LOGIN_CUSTOMER_ID"],
                                       "GOOGLE_ADS_LOGIN_CUSTOMER_ID"),
           "use_proto_plus": True}
    return GoogleAdsClient.load_from_dict(cfg, version=API_VERSION)


def _err(e):
    try:
        return "; ".join(f"{x.error_code}: {x.message}" for x in e.failure.errors)[:300]
    except Exception:
        return str(e)[:300]


def _search(client, cid, query):
    return list(client.get_service("GoogleAdsService").search(customer_id=cid, query=query))


def probe_read(client, cid):
    try:
        rows = _search(client, cid, """
            SELECT customer.id, customer.manager, customer.status, customer.test_account
            FROM customer LIMIT 1""")
        if not rows:
            return {"ok": False, "detail": "query succeeded but returned no rows"}
        c = rows[0].customer
        return {"ok": True, "manager": bool(c.manager), "status": str(c.status),
                "test_account": bool(c.test_account)}
    except GoogleAdsException as e:
        return {"ok": False, "detail": _err(e)}


def probe_scope(client, login_cid):
    """Blast radius: every account this credential can reach through the manager."""
    try:
        rows = _search(client, login_cid, """
            SELECT customer_client.id, customer_client.level, customer_client.manager,
                   customer_client.status
            FROM customer_client""")
        return {"ok": True,
                "reachable_accounts": len(rows),
                "managers": sum(1 for r in rows if r.customer_client.manager),
                "id_sha12": [sha12(r.customer_client.id) for r in rows]}
    except GoogleAdsException as e:
        return {"ok": False, "detail": _err(e)}


def probe_manager_admin(client, mcc):
    """Is this credential ADMIN at the manager level? Non-mutating.

    validate_only update of the MANAGER account's own descriptive_name, set to the
    value it already holds. Touches no client ad account, and validate_only means
    nothing is written even when accepted.

    This supersedes an earlier claim in this file that admin was not measurable. That
    claim was based on MutateCustomerUserAccessRequest lacking validate_only — true,
    but the wrong service to reach for. MutateCustomerRequest HAS validate_only, and
    updating the manager account is admin-gated, which makes it a sound probe.

    Verified discriminating: a credential known READ_ONLY on the manager is refused
    with ACTION_NOT_PERMITTED, while a manager ADMIN is accepted.
    """
    try:
        rows = _search(client, mcc, "SELECT customer.descriptive_name FROM customer LIMIT 1")
        if not rows:
            return {"admin": None, "reason": "could not read the manager account"}
        name = rows[0].customer.descriptive_name
    except GoogleAdsException as e:
        return {"admin": None, "reason": "manager read refused", "detail": _err(e)}

    from google.api_core import protobuf_helpers
    svc = client.get_service("CustomerService")
    op = client.get_type("CustomerOperation")
    op.update.resource_name = svc.customer_path(mcc)
    op.update.descriptive_name = name                 # unchanged value
    client.copy_from(op.update_mask, protobuf_helpers.field_mask(None, op.update._pb))
    req = client.get_type("MutateCustomerRequest")
    req.customer_id = mcc
    req.operation = op
    req.validate_only = True                          # HARDCODED — no flag
    try:
        svc.mutate_customer(request=req)
        return {"admin": True, "reason": "manager-level update accepted"}
    except GoogleAdsException as e:
        sig = _err(e)
        if classify_mutate_error(sig) is False:
            return {"admin": False, "reason": "authorization refusal"}
        return {"admin": None, "reason": "non-authorization refusal", "detail": sig}


def probe_roles(client, cid, label):
    """Google's own record of who holds what. Emails are hashed; only a 3-char hint
    is kept so a human can match a row to an account without the file carrying an
    address."""
    try:
        rows = _search(client, cid, """
            SELECT customer_user_access.user_id, customer_user_access.access_role,
                   customer_user_access.email_address
            FROM customer_user_access""")
        users = []
        for r in rows:
            a = r.customer_user_access
            email = a.email_address or ""
            local = email.split("@")[0] if "@" in email else ""
            users.append({"user_id": str(a.user_id),
                          "role": ACCESS_ROLE.get(int(a.access_role), str(a.access_role)),
                          "email_hint": (local[:3] + "…") if local else "?",
                          "email_sha12": sha12(email)})
        return {"ok": True, "level": label, "users": users, "count": len(users)}
    except GoogleAdsException as e:
        return {"ok": False, "level": label, "detail": _err(e)}


def classify_mutate_error(signature):
    """Map a Google Ads error signature to a three-valued authorization answer.

    Factored out and unit-tested because getting this wrong is exactly how an
    earlier version reported a mutate-capable credential as read-only: it treated
    OPERATION_NOT_PERMITTED_FOR_CONTEXT — which means "wrong campaign type for this
    operation" — as an authorization refusal. A context error says nothing about
    access level, and must stay INCONCLUSIVE rather than being rounded to a verdict.

    Returns False for an authorization refusal, None for anything else.
    """
    return False if any(code in signature for code in AUTH_DENIED) else None


def probe_mutate(client, cid):
    """validate_only ALWAYS — hardcoded. Selects a SEARCH campaign specifically:
    campaign-level negative keywords are invalid on some channel types, and that
    refusal is a CONTEXT error, not an authorization one. Conflating the two would
    report a read-only credential as mutate-capable, or vice versa."""
    try:
        camps = _search(client, cid, """
            SELECT campaign.id, campaign.status, campaign.advertising_channel_type
            FROM campaign
            WHERE campaign.advertising_channel_type = 'SEARCH'
            LIMIT 1""")
    except GoogleAdsException as e:
        return {"permitted": None, "reason": "campaign lookup refused", "detail": _err(e)}
    if not camps:
        return {"permitted": None,
                "reason": "no SEARCH campaign in this account — cannot reach an "
                          "authorization decision; treat as INCONCLUSIVE, not as read-only"}

    op = client.get_type("CampaignCriterionOperation")
    crit = op.create
    crit.campaign = client.get_service("CampaignService").campaign_path(cid, camps[0].campaign.id)
    crit.negative = True
    crit.keyword.text = "hermes access level probe"
    crit.keyword.match_type = client.enums.KeywordMatchTypeEnum.EXACT

    req = client.get_type("MutateCampaignCriteriaRequest")
    req.customer_id = cid
    req.operations = [op]
    req.validate_only = True                                   # HARDCODED — no flag
    try:
        client.get_service("CampaignCriterionService").mutate_campaign_criteria(request=req)
        return {"permitted": True, "reason": "validate_only mutate accepted"}
    except GoogleAdsException as e:
        sig = _err(e)
        permitted = classify_mutate_error(sig)
        reason = "authorization refusal" if permitted is False else "non-authorization refusal"
        return {"permitted": permitted, "reason": reason, "detail": sig}


def verdict(read, mutate):
    if not read["ok"]:
        return "UNUSABLE"
    if mutate.get("permitted") is True:
        return "MUTATE_CAPABLE"
    if mutate.get("permitted") is False:
        return "READ_ONLY"
    return "INCONCLUSIVE"


def main():
    env = os.environ
    label = env.get("CREDENTIAL_LABEL", "(unlabelled)")
    role_declared = env.get("GOOGLE_ADS_CREDENTIAL_ROLE", "").strip()
    declared = role_declared or "read (no role declared)"
    expected = "MUTATE_CAPABLE" if role_declared == "write" else "READ_ONLY"

    client = build_client(env)
    cid = digits(env["GOOGLE_ADS_CUSTOMER_ID"], "GOOGLE_ADS_CUSTOMER_ID")
    login = digits(env["GOOGLE_ADS_LOGIN_CUSTOMER_ID"], "GOOGLE_ADS_LOGIN_CUSTOMER_ID")

    read = probe_read(client, cid)
    scope = probe_scope(client, login) if read["ok"] else {"ok": False, "detail": "skipped"}
    mutate = probe_mutate(client, cid) if read["ok"] else {"permitted": None,
                                                           "reason": "skipped — read failed"}
    roles = [probe_roles(client, login, "manager (login_customer_id)"),
             probe_roles(client, cid, "target account")] if read["ok"] else []
    mgr_admin = probe_manager_admin(client, login) if read["ok"] else {"admin": None,
                                                                      "reason": "skipped"}

    v = verdict(read, mutate)
    mismatch = read["ok"] and v != "INCONCLUSIVE" and v != expected

    print(json.dumps({
        "label": label,
        "fingerprints": {
            "client_id_sha12": sha12(env["GOOGLE_ADS_CLIENT_ID"]),
            "refresh_token_sha12": sha12(env["GOOGLE_ADS_REFRESH_TOKEN"]),
            "customer_id_sha12": sha12(cid),
            "login_customer_id_sha12": sha12(login),
        },
        "declared_role": declared,
        "expected_verdict": expected,
        "measured_verdict": v,
        "mismatch": mismatch,
        "manager_level_admin": mgr_admin,
        "probes": {"read": read, "scope": scope, "mutate": mutate,
                   "manager_admin": mgr_admin, "roles": roles},
    }, indent=2))

    if v == "UNUSABLE":
        return 2
    if mismatch:
        return 3
    if v == "INCONCLUSIVE":
        return 4
    return 0


if __name__ == "__main__":
    sys.exit(main())
