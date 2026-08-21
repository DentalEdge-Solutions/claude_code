#!/usr/bin/env python3
"""Apply an approved change-set to a client's external Google Ads account.

THE ONLY CREDENTIALED ENTRY POINT in the mutation tier. Runs inside the ONE-SHOT
`ads-mutator` container — never the gateway — invoked by run-ads-mutate.sh, which
injects a SEPARATE Standard-access write credential per-invocation via
`docker compose run -e`. (It was `docker compose exec -e` into the long-lived gateway
until 2026-08-19; that put the credential in a container Hermes has a shell in, where
any same-UID process could read it from /proc/<pid>/environ.) Stdlib-only; the SDK
lives in the project's pinned venv, reached through the allow-listed mutator
subprocess.

Guard order is load-bearing (spec §7): every refusal happens BEFORE the credential is
used, so exit 2 is a promise that nothing was mutated. Exit 3 means at least one live
mutation landed; the audit log holds what did, and --undo can reverse it.

See docs/superpowers/specs/2026-08-12-hermes-mutation-tier-design.md
"""
import argparse, datetime, json, os, re, shutil, subprocess, sys, tempfile
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import changeset_lib as C
import vault_lib

CRED_VARS = ("GOOGLE_ADS_DEVELOPER_TOKEN", "GOOGLE_ADS_CLIENT_ID",
             "GOOGLE_ADS_CLIENT_SECRET", "GOOGLE_ADS_REFRESH_TOKEN",
             "GOOGLE_ADS_LOGIN_CUSTOMER_ID", "GOOGLE_ADS_CUSTOMER_ID")
SECRET_VARS = ("GOOGLE_ADS_DEVELOPER_TOKEN", "GOOGLE_ADS_CLIENT_ID",
               "GOOGLE_ADS_CLIENT_SECRET", "GOOGLE_ADS_REFRESH_TOKEN")
ROLE_VAR = "GOOGLE_ADS_CREDENTIAL_ROLE"
WRITE_ROLE = "write"

# Must match the mutator's own RESOURCE_RE — this side validates what comes BACK,
# before it is persisted as the reversibility record.
RESOURCE_RE = re.compile(r"^customers/[0-9]{1,15}/campaignCriteria/[0-9]{1,20}~[0-9]{1,20}$")

# Mirrors run-ads-report.py: the mutator gets the credentials plus a minimal benign
# runtime whitelist, and nothing else — never ANTHROPIC_API_KEY or the OpenRouter key.
_RUNTIME_ENV_KEYS = ("PATH", "HOME", "LANG", "LC_ALL", "LC_CTYPE", "TMPDIR", "TZ",
                     "SSL_CERT_FILE", "SSL_CERT_DIR", "GRPC_DEFAULT_SSL_ROOTS_FILE_PATH",
                     "REQUESTS_CA_BUNDLE")


class PostMutationError(Exception):
    """Raised for any failure AFTER at least one live mutation landed. Exits 3, never 2 —
    exit 2 must remain a guarantee that the account was not touched."""


def _utcnow():
    return datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0)


def _refuse(msg):
    print(f"apply-changeset: {msg}", file=sys.stderr)
    raise SystemExit(2)


def _scrub(text):
    for v in SECRET_VARS:
        s = os.environ.get(v)
        if s:
            text = text.replace(s, "***")
    return text


def _child_env():
    env = {k: os.environ[k] for k in _RUNTIME_ENV_KEYS if k in os.environ}
    for v in CRED_VARS:
        env[v] = os.environ[v]
    return env


def build_plan(client, changeset_id, now, registry=None, projects=None, undo=None):
    """Guards 1-8. Returns everything apply() needs; raises SystemExit(2) on any refusal."""
    target = undo or changeset_id
    if not C.CHANGESET_ID_RE.fullmatch(target or ""):
        _refuse(f"invalid change-set id: {target!r}")

    # 1. kill switch FIRST, before any per-client parsing — the mandated order is
    #    literal, not approximate. CREATING change only; undo must stay available so
    #    cleanup is never blocked by the switch that stopped the damage.
    if not undo and not C.kill_switch_ok():
        _refuse("mutation is disabled (kill switch absent or unreadable) — this is the safe default")

    # 2. client resolves and is active
    try:
        rec = vault_lib.resolve(client, registry)
    except (ValueError, KeyError, OSError, TypeError) as e:
        _refuse(str(e))
    vault = rec["vault_path"]
    if rec.get("status") != "active":
        _refuse(f"client status is {rec.get('status')!r}, not 'active'")

    projects_path = projects or C.registry_projects_path()
    try:
        cfg = C.read_mutate_execute(projects_path, rec["project"])
    except (ValueError, OSError) as e:
        _refuse(str(e))

    cs, approval, actions = None, None, []
    if undo:
        # Spec §7.1: resource_name is shape- and prefix-validated against the RESOLVED
        # customer_id inside _undo_targets, so no record can reach argv unvalidated.
        # Uses no credential, so it belongs here with the other cheap checks.
        actions = _undo_targets(rec["slug"], undo, rec["customer_id"])
        if not actions:
            _refuse(f"no applied, un-undone actions recorded for change-set {undo!r}")
        operator = actions[0].get("operator", "unknown")
    else:
        # 3. change-set loads and validates — from the APPROVED SNAPSHOT in the
        #    governance store, never the vault copy Hermes can write.
        path = C.snapshot_path(rec["slug"], changeset_id)
        if not os.path.isfile(path):
            _refuse(f"no approved change-set {changeset_id!r} for this client")
        try:
            with open(path, encoding="utf-8") as f:
                cs = json.load(f)
            C.validate_changeset(cs, cfg["caps"]["actions_per_changeset"])
        except (ValueError, json.JSONDecodeError) as e:
            _refuse(str(e))
        # 4. identity match — a tamper check, since propose supplies these fields
        if cs["client"] != rec["slug"] or cs["customer_id"] != rec["customer_id"] \
                or cs["project"] != rec["project"]:
            _refuse("change-set identity does not match the resolved client")
        # 5. approval
        try:
            approval = C.verify_approval(rec["slug"], changeset_id, C.file_digest(path), now)
        except (ValueError, OSError, json.JSONDecodeError) as e:
            _refuse(str(e))
        operator = approval["operator"]
        # 6. daily caps
        try:
            counts = C.day_counts(rec["slug"], now.strftime("%Y-%m-%d"))
        except ValueError as e:
            _refuse(str(e))
        if counts["applies"] + 1 > cfg["caps"]["applies_per_client_day"]:
            _refuse(f"daily applies cap reached ({counts['applies']}/"
                    f"{cfg['caps']['applies_per_client_day']})")
        if counts["actions"] + len(cs["actions"]) > cfg["caps"]["actions_per_client_day"]:
            _refuse(f"daily actions cap would be exceeded ({counts['actions']}+{len(cs['actions'])}"
                    f" > {cfg['caps']['actions_per_client_day']})")
        actions = cs["actions"]

    # 6b. The injected credential must belong to THIS client — on BOTH paths.
    #     Without this on the undo path, an undo for client A could run against
    #     client B's injected credential, and the only thing refusing it would be the
    #     mutator in a DIFFERENT repository. A pre-flight guarantee must not depend on
    #     code Hermes does not own.
    injected = "".join(c for c in os.environ.get("GOOGLE_ADS_CUSTOMER_ID", "") if c.isdigit())
    if rec["customer_id"] != injected:
        _refuse("injected GOOGLE_ADS_CUSTOMER_ID does not match this client's customer_id")

    # 7. allow-list resolution + disjointness
    if len(cfg["allow"]) != 1:
        _refuse(f"mutate_execute.allow must hold exactly one entry, got {cfg['allow']}")
    name = cfg["allow"][0]
    if os.path.basename(name) != name:
        _refuse(f"mutator name must be a bare basename, got {name!r}")
    try:
        C.assert_allow_lists_disjoint(
            C.read_allow_list(projects_path, rec["project"], "read_execute"), cfg["allow"])
        workdir = C.read_workdir(projects_path, rec["project"])
    except (ValueError, OSError) as e:
        _refuse(str(e))
    script = os.path.join(workdir, cfg["script_dir"], name + ".py")
    if not os.path.isfile(cfg["runner"]):
        _refuse(f"runner interpreter not found: {cfg['runner']}")
    if not os.path.isfile(script):
        _refuse(f"mutator not found: {script}")

    # 8. credentials
    missing = [v for v in CRED_VARS if not os.environ.get(v)]
    if missing:
        _refuse(f"missing injected credential vars: {', '.join(missing)} "
                "(operator-invoked via run-ads-mutate.sh only)")
    if os.environ.get(ROLE_VAR) != WRITE_ROLE:
        _refuse(f"{ROLE_VAR} is {os.environ.get(ROLE_VAR)!r}, expected {WRITE_ROLE!r} — "
                "the mutation tier refuses the read-only credential")

    return {"vault": vault, "slug": rec["slug"], "changeset_id": target, "runner": cfg["runner"],
            "script": script, "actions": actions, "undo": bool(undo), "operator": operator,
            "customer_id": rec["customer_id"]}


def _undo_targets(slug, changeset_id, customer_id):
    """Applied, un-undone actions for this change-set BELONGING TO THIS CUSTOMER.

    The customer_id argument is the spec §7.1 guard, and its placement here is
    deliberate. That guard also exists inside the ads-repo mutator's do_undo, but a
    pre-flight guarantee must not depend on code Hermes neither owns nor
    version-pins — the same reasoning the guard-6b comment above applies to the
    injected credential. Validating INSIDE this function, rather than in build_plan
    after it returns, means an unvalidated record cannot escape into argv at all.

    Records are read through C.iter_log_records so the undo path and the caps path
    share one parser with one standard of rigour, from the same governance-store
    log an operator's --undo targets — never a copy Hermes itself could steer.
    """
    try:
        records = list(C.iter_log_records(slug))
    except ValueError as e:
        _refuse(str(e))
    targets, undone = [], set()
    for n, r in records:
        if r["changeset_id"] != changeset_id:
            continue
        rn = r.get("resource_name")
        if not isinstance(rn, str) or not RESOURCE_RE.fullmatch(rn):
            _refuse(f"audit log at {C.log_path(slug)}:{n} has a malformed resource_name "
                    "— refusing to hand it to the mutator")
        if not rn.startswith(f"customers/{customer_id}/"):
            _refuse("refusing to undo a criterion that belongs to another customer "
                    "(spec §7.1: an undo can never reach another account)")
        if r["status"] == "applied":
            targets.append(r)
        elif r["status"] == "undone":
            undone.add(rn)
    return [r for r in reversed(targets) if r["resource_name"] not in undone]


def _invoke(plan, args, scratch):
    """Returns RAW (unscrubbed) stdout/stderr — the live-loop JSON payload must be
    parsed byte-exact. Scrubbing happens only where text is embedded into a
    human-facing message (_refuse / PostMutationError strings), never on the parse
    path: run-ads-report.py's whole-string _scrub() replaces every occurrence of a
    secret value anywhere in the text, and the mutator's success JSON legitimately
    contains ordinary substrings ("resource_name", "true", ...) that can coincide
    with a short placeholder credential — scrubbing the parse input would corrupt it."""
    proc = subprocess.run([plan["runner"], plan["script"]] + args,
                          cwd=scratch, env=_child_env(), capture_output=True, text=True)
    return proc.returncode, proc.stdout, proc.stderr


def apply(plan, now):
    scratch = tempfile.mkdtemp(prefix="ads-mutate-")   # defense in depth: no in-tree .env nearby
    try:
        # 9. validate_only over EVERY action, all-or-nothing.
        #    Any exception here is a REFUSAL (exit 2), not a usage error (exit 1): a
        #    validate_only call cannot mutate, so "nothing was touched" still holds even
        #    when the failure is an OSError spawning the runner rather than a rejection
        #    from Google. build_plan pre-checks that the runner exists, but it cannot
        #    pre-check permissions, exhaustion, or a mid-run OSError.
        try:
            for i, a in enumerate(plan["actions"]):
                args = (["--undo", a["resource_name"]] if plan["undo"]
                        else ["--action", json.dumps(a, sort_keys=True)]) + ["--validate-only"]
                rc, out, err = _invoke(plan, args, scratch)
                if rc != 0:
                    _refuse(f"validate_only failed for action {i} — nothing applied:\n{_scrub(err)}")
        except SystemExit:
            raise                      # the _refuse above already chose exit 2
        except Exception as e:
            _refuse(f"validate_only could not run for action {i} — nothing applied "
                    f"({type(e).__name__}: {_scrub(str(e))})")

        # 10. live, one action at a time, each logged before the next begins.
        # PostMutationError is caught HERE, at the boundary of apply() itself, and
        # converted to SystemExit(3) — not left to propagate as a bare exception and
        # not deferred to main(). apply() is called directly (not just via the CLI, see
        # apply-changeset.test.py), so the 0/2/3 exit-code contract has to hold at the
        # function boundary, the same way build_plan's refusals hold SystemExit(2) at
        # its own boundary rather than leaking a plain ValueError to callers.
        landed = False   # True once the mutator has RUN — the account may differ from here on
        try:
            results = []
            for i, a in enumerate(plan["actions"]):
                args = (["--undo", a["resource_name"]] if plan["undo"]
                        else ["--action", json.dumps(a, sort_keys=True)])
                rc, out, err = _invoke(plan, args, scratch)
                # Set BEFORE inspecting rc: a non-zero return means the mutator ran and
                # failed, which is not evidence that nothing changed. Conservative by design.
                landed = True
                if rc != 0:
                    raise PostMutationError(f"action {i} failed after {len(results)} already applied:\n{_scrub(err)}")
                try:
                    payload = json.loads(out)
                except json.JSONDecodeError:
                    raise PostMutationError(f"action {i} returned unparseable output — the mutation may "
                                            f"have landed; inspect the account:\n{_scrub(out)}")
                resource = payload.get("removed") if plan["undo"] else payload.get("resource_name")
                # Shape-validate before it becomes the durable reversibility record. This is
                # the one piece of subprocess output persisted verbatim, so a malfunctioning
                # mutator must not be able to write arbitrary text into the audit log.
                if not RESOURCE_RE.fullmatch(resource or ""):
                    raise PostMutationError(f"action {i} returned a malformed resource name "
                                            f"{_scrub(repr(resource))} — the mutation may have "
                                            f"landed; inspect the account")
                # ts comes from the run's `now`, deliberately, so every action in one apply
                # shares it. A whole-branch review suggested a fresh per-action timestamp for
                # audit precision; that was tried and reverted, because day_counts matches
                # this exact field to enforce the DAILY CAPS. A write-time clock decouples the
                # log from the cap accounting that reads it — deterministically under an
                # injected `now`, and across a UTC midnight in production, where actions
                # logged after 00:00 would stop counting toward the day the run was admitted
                # under. Sequence is already recoverable from action_index.
                rec = {"ts": now.strftime(C.ISO), "changeset_id": plan["changeset_id"],
                       "action_index": i, "type": a.get("type", "add_campaign_negative"),
                       "resource_name": resource,
                       "status": "undone" if plan["undo"] else "applied",
                       "operator": plan["operator"]}
                try:
                    C.append_log(plan["slug"], rec)  # fsync'd before the next action starts
                except Exception as e:
                    # The one place an irreversible side effect can outrun its record. Print
                    # the resource name FIRST: it is the only way back from here, and it is
                    # about to exist nowhere else.
                    print(f"apply-changeset: action {i} LANDED but its audit-log write failed. "
                          f"RECORD THIS NOW — it is in no log: {resource}", file=sys.stderr)
                    raise PostMutationError(f"audit-log write failed after action {i} landed: {_scrub(str(e))}")
                results.append(rec)

            # 11. Emit the run record for the CALLER to persist. This container does
            #     not mount the vault; the audit log above is the reversibility record.
            #     result.json and timeline.md are convenience artifacts written by
            #     persist-run-record.py from this line, never by the executor itself.
            result = {"changeset_id": plan["changeset_id"], "undo": plan["undo"],
                      "status": "ok", "finished_at": now.strftime(C.ISO),
                      "operator": plan["operator"], "applied": len(results),
                      "actions": results}
            print("HERMES-RESULT-JSON " + json.dumps(result, sort_keys=True))
            return 0
        except PostMutationError as e:
            print(f"apply-changeset: {e}", file=sys.stderr)
            print("apply-changeset: EXIT 3 — at least one mutation LANDED. The audit log records "
                  "what applied; reverse it with --undo.", file=sys.stderr)
            raise SystemExit(3)
        except SystemExit:
            # Belt-and-braces. SystemExit derives from BaseException, so the `except
            # Exception` below would not catch a _refuse() anyway — this clause exists so a
            # future widening to `except BaseException` cannot silently swallow a refusal
            # and relabel it as a post-mutation failure.
            raise
        except Exception as e:
            # Anything unexpected raised after the live loop began — an OSError writing
            # result.json, a full disk, a directory where timeline.md should be. Without
            # this, such a failure escaped apply() as a traceback and exit 1, which reads
            # as "usage error, nothing happened" for a run that DID change the account.
            # The exit code is chosen by what actually happened, never by the exception type.
            if landed:
                print(f"apply-changeset: {type(e).__name__} after a live mutation: {_scrub(str(e))}",
                      file=sys.stderr)
                print("apply-changeset: EXIT 3 — at least one mutation LANDED. The audit log records "
                      "what applied; reverse it with --undo.", file=sys.stderr)
                raise SystemExit(3)
            # Nothing was sent: subprocess.run raises before the child starts, so exit 2's
            # promise still holds.
            _refuse(f"failed before any mutation was attempted "
                    f"({type(e).__name__}: {_scrub(str(e))})")
    finally:
        shutil.rmtree(scratch, ignore_errors=True)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--client", required=True)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--changeset")
    g.add_argument("--undo")
    ap.add_argument("--registry")
    ap.add_argument("--projects")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)
    now = _utcnow()
    plan = build_plan(args.client, args.changeset, now, args.registry, args.projects, args.undo)
    if args.dry_run:
        print(f"vault:   {plan['vault']}")
        print(f"runner:  {plan['runner']}")
        print(f"script:  {plan['script']}")
        print(f"mode:    {'undo' if plan['undo'] else 'apply'}")
        print(f"actions: {len(plan['actions'])}")
        return 0
    # apply() itself raises SystemExit(2)/(3) on refusal or post-mutation failure — its
    # return value is only ever 0. No try/except needed here.
    return apply(plan, now)


if __name__ == "__main__":
    sys.exit(main())
