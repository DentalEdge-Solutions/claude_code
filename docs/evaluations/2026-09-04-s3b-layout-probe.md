# S3-b Layout Probe — Container-Measured Evidence

**Date:** 2026-09-04/05
**Branch:** `s3b-audit-log-integrity`
**Purpose:** `preflight-governance-access.py` is a deliberate no-op off Linux
(`applies()` returns `False` unless `sys.platform` startswith `linux`). A clean
run on macOS proves nothing about the POSIX layout — that exact mistake was
made in this project once already (a clean darwin exit 0 with no output was
reported as "zero problems — the requirement holds", when in fact the gate had
never run). The unit tests pass `platform="linux"` explicitly, which covers
the *logic*; nothing on the dev machine covers the *layout*. This document is
the container-measured evidence that closes that gap.

Image used throughout: `hermes-agent-claude:latest`.

**`ads-mutator` is the compose SERVICE name, not an image.**
`hermes-agent-claude:latest` is the only image that exists on this host, and
it is what `docker run` takes below.

---

## Step 1: Confirm the image exists and is the executor's real identity

Commands (verbatim):

```bash
docker images --format '{{.Repository}}:{{.Tag}}' | grep hermes-agent-claude
docker run --rm --entrypoint sh hermes-agent-claude:latest -c 'id hermes; python3 -VV; uname -s'
```

Raw output:

```
hermes-agent-claude:latest

uid=10000(hermes) gid=10000(hermes) groups=10000(hermes)
Python 3.13.5 (main, Jun 13 2026, 14:18:01) [GCC 14.2.0]
Linux
```

Full (untruncated) image id, captured separately for the record:

```
$ docker images --no-trunc --format '{{.Repository}}:{{.Tag}}\t{{.ID}}' | grep hermes-agent-claude
hermes-agent-claude:latest	sha256:3d362bb542c299d85e3905a66b83a459ee1e721f365acc3e836a5f788e96a42b
```

Result: matches expectation exactly — image exists, `hermes` is uid 10000 /
gid 10000, Python 3.13.5, `Linux`. This is the real executor identity the
rest of the probes run as.

---

## Step 2: Three-row matrix, each row with both probes (append control + delete probe)

Command (verbatim):

```bash
cd /Users/ericksicard/Projects/claude_code
docker run --rm --user 0:0 --entrypoint sh hermes-agent-claude:latest -c '
set -u
probe() {
  mode="$1"; gid="$2"; label="$3"
  root=$(mktemp -d)
  mkdir -p "$root/log"
  chmod 0755 "$root"                      # ancestors MUST be traversable, or append
                                          # fails for an irrelevant reason
  chgrp "$gid" "$root/log"
  chmod "$mode" "$root/log"
  : > "$root/log/slug-1.jsonl"
  chgrp "$gid" "$root/log/slug-1.jsonl"
  chmod 0660 "$root/log/slug-1.jsonl"
  if su hermes -s /bin/sh -c "printf x >> $root/log/slug-1.jsonl" 2>/dev/null; then
    append=OK; else append=DENIED; fi
  su hermes -s /bin/sh -c "rm -f $root/log/slug-1.jsonl" 2>/dev/null
  if [ -e "$root/log/slug-1.jsonl" ]; then delete=DENIED; else delete=DELETED; fi
  printf "%-34s append=%-7s delete=%s\n" "$label" "$append" "$delete"
  rm -rf "$root"
}
probe 0770 10000 "0770 (the finding)"
probe 2750 10000 "2750 + gid 10000 (the fix)"
probe 2750 0     "2750 + WRONG gid (D4 hazard)"
'
```

Raw output:

```
0770 (the finding)                 append=OK      delete=DELETED
2750 + gid 10000 (the fix)         append=OK      delete=DENIED
2750 + WRONG gid (D4 hazard)       append=DENIED  delete=DENIED
```

### Matrix as measured

| row | append | delete | matches expected? |
|---|---|---|---|
| `0770` | `OK` | `DELETED` | yes — reproduces the finding |
| `2750`, file gid 10000 | `OK` | `DENIED` | yes — the fix |
| `2750`, file gid 0 (wrong gid) | `DENIED` | `DENIED` | yes — proves the append control discriminates |

All three rows match the brief's expected table exactly. Row 2's `append=OK`
is the load-bearing cell — it shows uid 10000 (the real executor identity from
Step 1) can still append under `2750`/`0660`, while `delete=DENIED` shows the
missing group-write bit removes `unlink`. Row 3 shows the same `2750` mode
with the wrong group fails BOTH append and delete, which is what makes row 2's
success meaningful rather than a broken fixture where nothing works.

---

## Step 3, attempt 1: Real pre-flight and real bootstrap inside the container

This attempt used the brief's `build()` verbatim and hit a fixture bug (fully
diagnosed below). It is kept in full, unedited, as the record of that finding.
The corrected re-run is in the next section, "Step 3, attempt 2."

Command (verbatim, as originally specified in the brief):

```bash
cd /Users/ericksicard/Projects/claude_code
docker run --rm --user 0:0 -v "$PWD/infra/hermes-agent/bin":/bin-ro:ro \
  --entrypoint sh hermes-agent-claude:latest -c '
set -u
build() {
  root=$(mktemp -d); mkdir -p "$root/log" "$root/approvals" "$root/control" "$root/registry"
  chmod 0750 "$root"; chgrp -R 10000 "$root"
  for d in approvals control registry; do chmod 0750 "$root/$d"; done
  chmod "$1" "$root/log"
  printf "{\"clients\": {}}" > "$root/registry/clients.json"
  chmod 0640 "$root/registry/clients.json"
  echo "$root"
}
for mode in 0770 2750; do
  root=$(build "$mode")
  out=$(python3 /bin-ro/preflight-governance-access.py --root "$root" 2>&1); rc=$?
  printf "empty registry, log/ %s -> exit %s\n" "$mode" "$rc"
  printf %s "$out" | head -3
  rm -rf "$root"
done

# The D2 refusal, and then the positive control that the guard still ADMITS.
root=$(build 2750)
printf "{\"clients\": {\"slug-1\": {\"status\": \"active\"}}}" > "$root/registry/clients.json"
chmod 0640 "$root/registry/clients.json"
out=$(python3 /bin-ro/preflight-governance-access.py --root "$root" 2>&1); rc=$?
printf "registered, no log -> exit %s (names bootstrap-logs: %s)\n" \
  "$rc" "$(printf %s "$out" | grep -c bootstrap-logs)"
python3 /bin-ro/migrate-governance.py --bootstrap-logs --governance-root "$root" --apply
out=$(python3 /bin-ro/preflight-governance-access.py --root "$root" 2>&1); rc=$?
printf "after bootstrap -> exit %s\n" "$rc"
ls -ln "$root/log"
rm -rf "$root"
'
```

Raw output (verbatim, exactly as produced by the command above):

```
empty registry, log/ 0770 -> exit 2
preflight-governance-access: the ads-mutator executor (uid 10000) cannot use the governance store. Refusing BEFORE any mutation, because this same condition reached mid-apply is an exit-3 failure after a live account change:
  - /tmp/tmp.ryNXBMa4Ew/registry/clients.json: mode 0640 owner 0:0 gives uid 10000 only --- — the executor needs read

empty registry, log/ 2750 -> exit 2
preflight-governance-access: the ads-mutator executor (uid 10000) cannot use the governance store. Refusing BEFORE any mutation, because this same condition reached mid-apply is an exit-3 failure after a live account change:
  - /tmp/tmp.NpdlxwxsFl/registry/clients.json: mode 0640 owner 0:0 gives uid 10000 only --- — the executor needs read

registered, no log -> exit 2 (names bootstrap-logs: 2)
{
  "created": [
    "slug-1"
  ],
  "skipped": []
}
after bootstrap -> exit 2
total 0
-rw-rw---- 1 0 10000 0 Sep  5 14:15 slug-1.jsonl
```

### FINDING: Step 3 as specified does not reproduce the expected table

The brief's expected outcome was: both empty-registry rows exit 0, then
`registered, no log -> exit 2` naming `--bootstrap-logs`, then
`after bootstrap -> exit 0` with `ls -ln` showing `-rw-rw----` group `10000`.

What was actually measured: **every** invocation across all three scenarios
exits 2, including the final one after the bootstrap ran. This is reported as
a finding per the brief's own instruction ("report it and stop rather than
tuning the probe until it matches"), not adjusted to force a green result.

**This is not R24(a).** R24(a) is the pre-Task-1 scenario where the `2750` row
fails specifically on the `log/` read+write+traverse problem. The refusal text
measured here names a different file — `registry/clients.json` — and it
appears identically in both the `0770` and `2750` empty-registry rows, so it
cannot be a `log/`-layout regression (Tasks 1–4 are confirmed landed, and the
`0770`/`2750` rows produce byte-identical refusal text on this axis).

**Root cause, established by direct diagnosis** (not by altering the probe —
this reruns the *same* `build()` logic and only adds visibility):

```bash
docker run --rm --user 0:0 --entrypoint sh hermes-agent-claude:latest -c '
set -u
root=$(mktemp -d); mkdir -p "$root/log" "$root/approvals" "$root/control" "$root/registry"
chmod 0750 "$root"; chgrp -R 10000 "$root"
for d in approvals control registry; do chmod 0750 "$root/$d"; done
ls -ln "$root"
printf "{\"clients\": {}}" > "$root/registry/clients.json"
ls -ln "$root/registry"
chmod 0640 "$root/registry/clients.json"
ls -ln "$root/registry"
rm -rf "$root"
'
```

Output:

```
total 16
drwxr-x--- 2 0 10000 4096 Sep  5 14:15 approvals
drwxr-x--- 2 0 10000 4096 Sep  5 14:15 control
drwxr-xr-x 2 0 10000 4096 Sep  5 14:15 log
drwxr-x--- 2 0 10000 4096 Sep  5 14:15 registry
total 4
-rw-r--r-- 1 0 0 15 Sep  5 14:15 clients.json
total 4
-rw-r----- 1 0 0 15 Sep  5 14:15 clients.json
```

The `registry/` directory is group `10000` (from the earlier `chgrp -R`), but
it is `0750` — **no setgid bit**. `clients.json` is created *after* that
`chgrp -R`, so it inherits the creating process's primary group (`root`,
gid 0), not the parent directory's group. The brief's `build()` helper never
`chgrp`s the file itself, only the pre-existing directories. Every scenario in
Step 3 therefore hits the pre-flight's independent `registry/clients.json`
readability check (`READ_ONLY_DIRS = ("approvals", "control", "registry")` in
`preflight-governance-access.py`) before the `log/`-layout logic is ever
reached — this readability check is real, intentional behavior in the
pre-flight (confirmed by reading the script; it is not a bug in the code under
test), but the brief's fixture never satisfies it.

**What this run does and does not show, precisely:**

- It does **not** demonstrate the intended CLI-level positive control (refuse
  → bootstrap → admit, ending in exit 0). That specific chain could not be
  observed in this session because of the fixture defect above, which is
  orthogonal to the `log/` permission work under test.
- It **does** independently corroborate two things Step 3 was also meant to
  show, visible directly in the raw output above regardless of the exit-code
  fixture bug:
  - The `registered, no log` refusal (full text captured below) correctly
    identifies the missing per-client log **and** names
    `migrate-governance.py --bootstrap-logs --apply` as the remedy.
  - `migrate-governance.py --bootstrap-logs --apply` actually ran and created
    `slug-1.jsonl` at **`-rw-rw---- 1 0 10000`** — mode `0660`, group `10000`
    — exactly the target layout, confirming the bootstrap mechanism itself
    (Task 3 of this wave) produces the correct file.

Full refusal text for the `registered, no log` step (captured in a follow-up
run using the identical `build(2750)` / registration logic, with the message
printed in full instead of grepped for a count — no parameters, ordering, or
inputs were changed):

```
preflight-governance-access: the ads-mutator executor (uid 10000) cannot use the governance store. Refusing BEFORE any mutation, because this same condition reached mid-apply is an exit-3 failure after a live account change:
  - /tmp/tmp.gFLCiRzMOY/registry/clients.json: mode 0640 owner 0:0 gives uid 10000 only --- — the executor needs read
  - /tmp/tmp.gFLCiRzMOY/log: 1 registered client(s) have no pre-created audit log. The executor cannot create one (log/ is host-owned 2750 by design), so this surfaces mid-apply as exit 3 after a live account change. Fix with: migrate-governance.py --bootstrap-logs --apply

Fix by OWNERSHIP, not by widening the mode. Either run the store under a group the
executor's UID belongs to:

    sudo chgrp -R 10000 /tmp/tmp.gFLCiRzMOY
    sudo chmod -R g+rX /tmp/tmp.gFLCiRzMOY
    sudo chmod g+s /tmp/tmp.gFLCiRzMOY/log
    sudo find /tmp/tmp.gFLCiRzMOY/log -type f -name '*.jsonl' -exec chmod 0660 {} +

log/ gets NO group write: write on a directory is what grants unlink, and a deleted
audit log costs reversibility (both --undo and the daily caps read through it), not
merely quota. The executor appends to a PRE-CREATED per-client file instead, and setgid
on log/ is what makes host-created files inherit gid 10000 — without it, 0660 grants
the wrong group and uid 10000 falls through to `other`. Create missing per-client logs
with:

    migrate-governance.py --bootstrap-logs --apply

or give the store to the executor's UID outright:

    sudo chown -R 10000:10000 /tmp/tmp.gFLCiRzMOY && sudo chmod -R 700 /tmp/tmp.gFLCiRzMOY

Do NOT `chmod 777`. The store is the one place Hermes cannot reach; making it
world-writable hands it to every process on the host and removes the isolation this
whole tier is built on.
```

`after bootstrap` output (same follow-up run) — the persisting refusal is now
*only* the pre-existing `registry/clients.json` bullet (the `log/` bullet is
gone, i.e. the bootstrap resolved the log-side condition):

```
preflight-governance-access: the ads-mutator executor (uid 10000) cannot use the governance store. Refusing BEFORE any mutation, because this same condition reached mid-apply is an exit-3 failure after a live account change:
  - /tmp/tmp.gFLCiRzMOY/registry/clients.json: mode 0640 owner 0:0 gives uid 10000 only --- — the executor needs read
```

and:

```
total 0
-rw-rw---- 1 0 10000 0 Sep  5 14:17 slug-1.jsonl
```

This last pair is the clearest evidence in the whole probe: after bootstrap,
the ONLY remaining refusal reason is the unrelated registry fixture bug — the
`log/`-side condition that Task 3 targets is fully resolved, and the created
file is at the exact target mode/group. Had the brief's `build()` helper
either applied setgid to `registry/` before creating `clients.json`, or
`chgrp`'d the file explicitly (the same fix it already applies to
`log/*.jsonl`), this run would very likely have produced the full green
end-to-end sequence the brief describes. That fix was **not** applied here,
in keeping with the instruction to report a divergent row as a finding rather
than tune the probe to match.

**Conclusion for Step 3:** the underlying layout mechanism this wave built
(Task 2's `2750` constants, Task 3's `--bootstrap-logs`) checks out under
direct inspection of the raw output, but the CLI-level end-to-end positive
control that Step 3 was designed to produce as a single clean exit-0 result
could not be completed in this session, because the brief's own fixture script
has a group-inheritance bug in its `registry/clients.json` setup that is
independent of the code under test. This should be corrected in the brief (or
the fixture re-run with `chmod g+s "$root/registry"` before writing
`clients.json`, or an explicit `chgrp 10000 "$root/registry/clients.json"`
after) before this exact end-to-end exit-0 sequence can be captured.

**This is a finding in its own right, not merely a fixture note — it is D4,
reproduced live.** The wave's coordinator confirmed the root cause against the
brief: `build()` runs `chgrp -R 10000 "$root"` and only afterward writes
`registry/clients.json`, and `registry/` carries no setgid bit to correct for
that ordering, so the new file inherits the creating process's gid (0) instead
of the parent directory's group (10000). That is the *exact same*
setgid-inheritance hazard — spec deviation D4 — that this entire wave exists
to close for `log/`, reproduced by accident in a different directory of the
probe's own fixture. It is independent, unplanned corroboration that D4 is
real and easy to hit even by someone who already knows about it and is trying
to avoid it, and it is the argument for D4's "verify what you created" rule
over trusting a README line describing the intended order of operations.
Refusing to tune the probe until it went green — reporting the refusal and its
cause instead — is what preserved this as usable evidence rather than erasing
it under a quick fix.

---

## Step 3, attempt 2: corrected fixture, re-run

Root cause from attempt 1: `clients.json` was created *after* the recursive
`chgrp -R 10000 "$root"` in `build()`, so it never got group `10000`. The fix
is ordering only — no logic change, and it matches the order the README's
deploy actually uses, where the store's files already exist when the operator
runs `chgrp -R` over the whole tree. The unrealistic order was the original
one, not this one.

Three changes to the Step 3 script, all mechanical (ordering, plus one added
print — no logic, threshold, or expectation changed):

1. In `build()`, create and `chmod` `clients.json` *before* the `chgrp -R`.
2. In the second block, where `clients.json` is overwritten with the `slug-1`
   registration (which happens *after* `build()`'s `chgrp -R` already ran),
   add an explicit `chgrp 10000` on that rewritten file.
3. Immediately after the `registered, no log` summary line, `printf '%s\n'
   "$out"` so the refusal text the block prints below is actually emitted by
   the command shown, rather than being captured into `$out` and only
   grep-counted. (A prior version of this section printed that text without
   this line present in the shown command — an undisclosed splice, flagged in
   review. This version's command and output now match exactly.)

Command (verbatim, corrected — this is the exact command that produced the
raw output immediately below, with nothing added or removed after the run):

```bash
cd /Users/ericksicard/Projects/claude_code
docker run --rm --user 0:0 -v "$PWD/infra/hermes-agent/bin":/bin-ro:ro \
  --entrypoint sh hermes-agent-claude:latest -c '
set -u
build() {
  root=$(mktemp -d); mkdir -p "$root/log" "$root/approvals" "$root/control" "$root/registry"
  printf "{\"clients\": {}}" > "$root/registry/clients.json"
  chmod 0640 "$root/registry/clients.json"
  chmod 0750 "$root"; chgrp -R 10000 "$root"
  for d in approvals control registry; do chmod 0750 "$root/$d"; done
  chmod "$1" "$root/log"
  echo "$root"
}
for mode in 0770 2750; do
  root=$(build "$mode")
  out=$(python3 /bin-ro/preflight-governance-access.py --root "$root" 2>&1); rc=$?
  printf "empty registry, log/ %s -> exit %s\n" "$mode" "$rc"
  printf %s "$out" | head -3
  rm -rf "$root"
done

# The D2 refusal, and then the positive control that the guard still ADMITS.
root=$(build 2750)
printf "{\"clients\": {\"slug-1\": {\"status\": \"active\"}}}" > "$root/registry/clients.json"
chgrp 10000 "$root/registry/clients.json"   # rewritten AFTER build()'s chgrp -R, so redo it
chmod 0640 "$root/registry/clients.json"
out=$(python3 /bin-ro/preflight-governance-access.py --root "$root" 2>&1); rc=$?
printf "registered, no log -> exit %s (names bootstrap-logs: %s)\n" \
  "$rc" "$(printf %s "$out" | grep -c bootstrap-logs)"
printf "%s\n" "$out"
python3 /bin-ro/migrate-governance.py --bootstrap-logs --governance-root "$root" --apply
out=$(python3 /bin-ro/preflight-governance-access.py --root "$root" 2>&1); rc=$?
printf "after bootstrap -> exit %s\n" "$rc"
ls -ln "$root/log"
rm -rf "$root"
'
```

Raw output (verbatim, exactly as produced by the command immediately above —
re-run for this fix round, so the temp path below is a fresh `mktemp -d` and
differs from any path shown elsewhere in this document; that is expected and
is not hand-edited to match):

```
empty registry, log/ 0770 -> exit 0
empty registry, log/ 2750 -> exit 0
registered, no log -> exit 2 (names bootstrap-logs: 2)
preflight-governance-access: the ads-mutator executor (uid 10000) cannot use the governance store. Refusing BEFORE any mutation, because this same condition reached mid-apply is an exit-3 failure after a live account change:
  - /tmp/tmp.mlYlWSvJny/log: 1 registered client(s) have no pre-created audit log. The executor cannot create one (log/ is host-owned 2750 by design), so this surfaces mid-apply as exit 3 after a live account change. Fix with: migrate-governance.py --bootstrap-logs --apply

Fix by OWNERSHIP, not by widening the mode. Either run the store under a group the
executor's UID belongs to:

    sudo chgrp -R 10000 /tmp/tmp.mlYlWSvJny
    sudo chmod -R g+rX /tmp/tmp.mlYlWSvJny
    sudo chmod g+s /tmp/tmp.mlYlWSvJny/log
    sudo find /tmp/tmp.mlYlWSvJny/log -type f -name '*.jsonl' -exec chmod 0660 {} +

log/ gets NO group write: write on a directory is what grants unlink, and a deleted
audit log costs reversibility (both --undo and the daily caps read through it), not
merely quota. The executor appends to a PRE-CREATED per-client file instead, and setgid
on log/ is what makes host-created files inherit gid 10000 — without it, 0660 grants
the wrong group and uid 10000 falls through to `other`. Create missing per-client logs
with:

    migrate-governance.py --bootstrap-logs --apply

or give the store to the executor's UID outright:

    sudo chown -R 10000:10000 /tmp/tmp.mlYlWSvJny && sudo chmod -R 700 /tmp/tmp.mlYlWSvJny

Do NOT `chmod 777`. The store is the one place Hermes cannot reach; making it
world-writable hands it to every process on the host and removes the isolation this
whole tier is built on.
{
  "created": [
    "slug-1"
  ],
  "skipped": []
}
after bootstrap -> exit 0
total 0
-rw-rw---- 1 0 10000 0 Sep  5 14:29 slug-1.jsonl
```

### Matrix as measured (attempt 2)

| check | expected | measured | matches? |
|---|---|---|---|
| empty registry, `log/` `0770` | exit 0 (over-grants, honest negative) | exit 0 | yes |
| empty registry, `log/` `2750` | exit 0 (now the supported layout) | exit 0 | yes |
| registered, no log | exit 2, naming `--bootstrap-logs` | exit 2, names it (2 occurrences) | yes |
| after `migrate-governance.py --bootstrap-logs --apply` | exit 0 | exit 0 | yes |
| `ls -ln "$root/log"` after bootstrap | `-rw-rw----` group `10000` | `-rw-rw---- 1 0 10000` | yes |

**The final `exit 0` was reached.** This is the load-bearing line the wave's
positive control depends on — the dual of "can an attacker get in?" that a
seam review in this project once failed to ask, passing a seam CLEAN that
nobody could actually get through. Here, the legitimate caller (a registered
client after a correct bootstrap) is admitted, not merely the illegitimate
caller refused.

**Conclusion for Step 3 (final):** with the fixture's own ordering bug
corrected (an ordering fix only, matching the README's real deploy sequence,
not a change to any threshold or expectation), the full end-to-end sequence
described in the brief is reproduced exactly: refusal naming
`--bootstrap-logs`, bootstrap creates the per-client log, and the guard then
admits the legitimate case at `exit 0` with the file at `-rw-rw----` group
`10000`. Combined with Step 2's clean three-row matrix, this closes the loop:
the OS-level permission model, the CLI-level refusal, and the CLI-level admit
all measure as designed for uid 10000 under Linux.

---

## What this does and does not establish

**Establishes:** append-but-not-unlink holds at the OS level for uid 10000 on
Linux at `2750`/`0660` (Step 2, all three rows matched the expected table
exactly, including the wrong-gid control row that proves the append check
discriminates rather than being a broken fixture). The pre-flight admits that
layout, and does so as the *end* of a real refuse → bootstrap → admit cycle:
Step 3 attempt 2 (with only an ordering fix to the probe's own fixture, no
change to the code under test or to any threshold) reproduced the brief's full
expected sequence exactly — both empty-registry rows exit 0, `registered, no
log` exits 2 naming `--bootstrap-logs`, the bootstrap creates `slug-1.jsonl`,
and the guard then admits the legitimate case at `exit 0` with the file at
`-rw-rw----` group `10000`. The wrong-gid row in Step 2 proves the append
control discriminates, so the fix row's success is evidence rather than a
coincidence, and Step 3's final `exit 0` is evidence that the guard admits the
legitimate caller, not merely that it refuses the illegitimate one.

**A finding surfaced along the way, kept in full:** Step 3 attempt 1 (using
the brief's `build()` verbatim) failed every scenario, including the final
one, on an unrelated real pre-flight check — `registry/clients.json` was
created after `build()`'s recursive `chgrp -R 10000`, and `registry/` has no
setgid bit to correct for that ordering, so the file inherited gid 0 instead
of 10000. This is the *same* setgid-inheritance hazard (spec deviation D4)
that this wave exists to close for `log/`, reproduced independently and by
accident in a different directory of the probe's own fixture — corroboration
that D4 is real and easy to hit even by someone actively guarding against it,
and the argument for D4's "verify what you created" rule over trusting a
README's stated order of operations. That attempt is preserved above,
unedited, with its full `ls -ln` diagnosis.

**Does NOT establish anything about the VPS.** This ran under Docker Desktop,
which remaps bind-mount ownership. Per R22 no darwin-hosted measurement may be
read as covering the VPS, whose bind-mount semantics Phase B owns. Nothing
here licenses describing Phase A as deployed or deployable.
