# D10.6 compares what the MCP block means, not how it is laid out: Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Review item D10.6 passes on a healthy box and still fails on a changed MCP configuration.

**What happened (first box rollout, 2026-10-02):** `data/config.yaml` was installed from
`config.yaml.example`. The gateway then rewrote the file (it added an `onboarding:` key and re-serialised the
whole document). The `mcp_servers:` block kept its content and key order but changed layout: quotes dropped,
the two flow lists written one item per line. The collector's line-for-line comparison reported
`equals_repo: false, lines: 16`, which checklist v1.12 makes a FAIL. Re-installing the template does not hold:
the gateway rewrites it again.

The block on the box, verbatim (it holds no secret):

```yaml
mcp_servers:
  ads_audit:
    command: python3
    args:
      - /opt/cc-bin/hermes-app-mcp.py
      - --app
      - ads-audit
    env: {}
    timeout: 360
    tools:
      include:
        - ads_audit_run
        - ads_audit_status
        - ads_audit_list
      resources: false
      prompts: false
```

and the file's top-level keys, in order: `model:`, `terminal:`, `provider_routing:`, `mcp_servers:`,
`onboarding:`.

**Architecture:** the collector parses the `mcp_servers:` block of both files with a small, strict parser for
the YAML subset those two layouts use, and compares the parsed values. Anything outside the subset is not
equal, with a reason from a closed set. It also requires every top-level key of the box file to be a plain
name and `mcp_servers` to appear exactly once, which closes the limit v1.12 had to state (a second key in
another YAML spelling). The box file is hostile input and none of its text is emitted.

**Tech Stack:** Python 3 stdlib only (no YAML library on the box).

**Spec:** `docs/superpowers/specs/2026-09-30-hermes-chat-triggered-audits-design.md` §8.1, D10.6: "Hermes MCP
config `tools.include` is exactly the three tools; the measured tool list is recorded as information, not a
boundary."

## Global Constraints

- Python stdlib only; tests are `bin/<name>.test.py`. `infra/hermes-agent/bin/run-bin-tests.sh` must end
  `N/N suites passed`.
- Bundles never contain a customer id, a slug, a credential value, a key, a hostname or report text. No text
  from `data/config.yaml` reaches the bundle: only booleans, counts, a closed-set reason and a sha256.
- The box file is read through `app_lib.read_capped` as today (no symlink, regular file, size cap); a refusal
  is could-not-check.
- Fail closed: a file or block the parser cannot fully account for is NOT equal. The parser never guesses.
- The parser never raises on any input: every failure is a reason.
- `CHECKLIST.md` changes, so its `version:` rises exactly once, to `1.13`.
- `config.yaml.example` does not change.

## Review Focus

1. **The healthy box.** The block above (rewritten layout) must compare equal to the template's block (flow
   lists, quoted `"python3"`). Test: `test_the_rewritten_layout_equals_the_template`.
2. **A changed value in the rewritten layout.** A fourth tool in `include`, a different `command`, a non-empty
   `env`, `resources: true`, a second server: each must be not equal. Test: `test_any_changed_value_differs`.
3. **Type confusion.** `timeout: "360"` vs `360`, `resources: "false"` vs `false`, `prompts: 0` vs `false`:
   not equal. YAML 1.1 words that a real loader would turn into booleans or null (`yes`, `no`, `on`, `off`,
   `null`, `~`, any case) and numbers with a leading zero or a decimal point are outside the subset:
   unparseable. Test: `test_types_are_compared_exactly`.
4. **Another spelling of the key, anywhere in the file.** A top-level line that is not blank, not a comment and
   not a plain `name:` key (a quoted or escaped key, a tag, an anchor, `? key`, `<<:`, `---`, a flow mapping, a
   continuation line at column 0), or a second plain `mcp_servers:`: not equal, with its reason. Test:
   `test_top_level_must_be_plain_and_single`.
5. **Hostile shapes.** Tabs, anchors and aliases, tags, block scalars (`|`, `>`), flow mappings other than
   `{}`, nested flow lists, an inline comment after a value, a duplicate key inside the block, a list item
   under a scalar, 10,000 levels of indentation, a 64 KiB line, binary bytes: a reason, never an exception, and
   quickly. Test: `test_hostile_blocks_are_unparseable_not_a_crash`.

---

## File Structure

| File | Status | Responsibility |
|---|---|---|
| `infra/hermes-agent/bin/mcp_config.py` (+ `.test.py`) | create | the strict subset parser and the comparison; no I/O |
| `infra/hermes-agent/bin/collect-review-evidence.py` (+ tests) | modify | `d10_6` uses it; `_mcp_block`, `_block_sha256`, `_MCP_KEY_RE` go |
| `infra/hermes-agent/deploy/security-review/CHECKLIST.md` | modify | v1.13; D10.6's claim, expected and pass rule |
| `infra/hermes-agent/bin/security-review-checklist.test.py` | modify | the pinned value test follows the new key |
| `infra/hermes-agent/deploy/BRING-UP.md` | modify | one sentence: the gateway rewrites `data/config.yaml`; D10.6 compares content |

---

### Task 3: `mcp_config.py`, the strict parser and comparison

**Files:**
- Create: `infra/hermes-agent/bin/mcp_config.py`, `infra/hermes-agent/bin/mcp_config.test.py`

**Interfaces:**
- Produces:
  - `REASONS = ("-", "no_block", "duplicate_key", "top_level_not_plain", "unparseable", "differs")`
  - `block_value(text: str) -> (value, reason)`: the parsed value of the file's `mcp_servers:` block (the
    mapping under that key), or `(None, reason)` with reason one of `no_block`, `duplicate_key`,
    `top_level_not_plain`, `unparseable`. Never raises.
  - `canonical(value) -> str`: `json.dumps(value, sort_keys=True, separators=(",", ":"))`. Mapping key ORDER
    does not matter; list order does; `true` and `1`, `"360"` and `360` are different.
  - `compare(box_text: str, repo_text: str) -> dict`:
    `{"equals_repo": bool, "reason": <one of REASONS>, "canonical_sha256": <hex or None>}`.
    `canonical_sha256` is of the BOX block's canonical form when it parsed, else `None`. `reason` is `-` when
    equal, `differs` when both parsed and differ, otherwise the box's reason. If the REPO text has no block or
    does not parse, raise `ValueError` (the caller makes it could-not-check): the template is ours.

**The subset (everything else is `unparseable`).** State it in the module docstring exactly:
- Lines are split on `\n`; a trailing `\r` is unparseable. Blank lines and lines whose first non-space
  character is `#` are skipped. A tab anywhere in a line's indentation is unparseable.
- The block is the top-level line `mcp_servers:` (nothing after the colon but spaces) and the indented lines
  that follow it, up to the next top-level line.
- Top level of the WHOLE file: every line starting at column 0 that is not blank or a comment must match
  `[A-Za-z_][A-Za-z0-9_-]*:` followed by end of line or a space. Otherwise `top_level_not_plain`. Exactly one
  such key may be `mcp_servers`; none is `no_block`, more than one is `duplicate_key`.
- Inside the block, by indentation (spaces only; a child is indented more than its parent; siblings share an
  indent):
  - mapping entry: `key:` followed by end of line (its value is the nested mapping or list that follows; if
    nothing follows it is unparseable) or `key: <scalar>` or `key: <flow>`. Keys match
    `[A-Za-z_][A-Za-z0-9_-]*`, unquoted. A repeated key in one mapping is `duplicate_key`.
  - block list item: `- <scalar>`. Items of one list share an indent, which is at least the indent of the key
    they belong to. Items are scalars only.
  - flow: `{}` (empty mapping), `[]` (empty list), or `[a, b, c]` whose items are scalars (no nesting, no
    trailing comma).
  - scalars:
    - `true` / `false` (lower case only) → bool;
    - `0` or `[1-9][0-9]*` → int;
    - `"..."` with no backslash and no `"` inside, or `'...'` with no `'` inside → that string;
    - a plain string matching `[A-Za-z0-9_./-]+` that contains at least one letter and is not, in any case, one
      of `true false yes no on off null y n` → that string. (So `python3`, `--app`, `ads-audit`,
      `/opt/cc-bin/hermes-app-mcp.py` and `ads_audit_run` parse; `Yes`, `0360`, `3.5`, `~` do not.)
  - nothing may follow a value on its line (no inline comment).
- Limits: more than 200 lines in the block, a line over 2,000 characters, or nesting deeper than 8 is
  unparseable. The parser is iterative or bounded: it must not recurse on input depth.

- [ ] **Step 1: Write the failing tests** (`mcp_config.test.py`), named as in Review Focus, plus:
  - `test_the_template_parses_to_the_expected_value`: the real `config.yaml.example` block parses to
    `{"ads_audit": {"command": "python3", "args": ["/opt/cc-bin/hermes-app-mcp.py", "--app", "ads-audit"],
    "env": {}, "timeout": 360, "tools": {"include": ["ads_audit_run", "ads_audit_status", "ads_audit_list"],
    "resources": False, "prompts": False}}}`.
  - `test_key_order_does_not_matter_list_order_does`.
  - `test_comments_and_blank_lines_in_the_block_are_ignored`.
  - `test_indentless_list_items_parse` (`args:` then `- x` at the SAME indent as `args:`, PyYAML's default).
  - `test_no_block_and_missing_file_text` (empty text, text with no `mcp_servers:`, `mcp_servers:` with nothing
    under it, `mcp_servers: {}`).
  - `test_compare_reports_the_boxs_reason_and_sha`.
  - `test_repo_text_without_a_block_raises_valueerror`.
  - `test_never_raises_on_fuzz`: for a few thousand random strings built from the characters of the real
    block plus `&*!|>{}[],'"#:\t-? ` and newlines, `block_value` returns a 2-tuple whose reason is in
    `REASONS` and never raises; seed the RNG so a failure reproduces.
  The rewritten layout and the template text used in the tests are the two blocks in this plan, inside whole
  files with other top-level keys before and after.

- [ ] **Step 2: Run to verify they fail** — `python3 infra/hermes-agent/bin/mcp_config.test.py -v` →
  `ModuleNotFoundError`/`FileNotFoundError` for `mcp_config.py`.

- [ ] **Step 3: Implement `mcp_config.py`** to the subset above. No I/O, no imports beyond `hashlib`, `json`,
  `re`. Keep it small and readable: a tokenising pass (indent, kind, key, value per line) and a stack-based
  build.

- [ ] **Step 4: Run to verify they pass**, then `infra/hermes-agent/bin/run-bin-tests.sh` (the new suite is
  discovered: expect `54/54 suites passed`).

- [ ] **Step 5: Commit**

```bash
git add infra/hermes-agent/bin/mcp_config.py infra/hermes-agent/bin/mcp_config.test.py
git commit -m "feat(hermes): strict parser for the MCP config block (D10.6 compares content, not layout)"
```

---

### Task 4: `d10_6` uses it; checklist v1.13

**Files:**
- Modify: `infra/hermes-agent/bin/collect-review-evidence.py`, `infra/hermes-agent/bin/collect-review-evidence.test.py`
- Modify: `infra/hermes-agent/deploy/security-review/CHECKLIST.md`, `infra/hermes-agent/bin/security-review-checklist.test.py`
- Modify: `infra/hermes-agent/deploy/BRING-UP.md`

**Interfaces:**
- Consumes: `mcp_config.compare`, `mcp_config.REASONS`.
- Produces: D10.6 data
  `{"mcp_block": {"equals_repo": bool, "reason": <REASONS>, "canonical_sha256": <hex|null>},
    "gateway_mcp_list": [...], "gateway_mcp_list_rc": <int|null>}`. The old `lines` and `sha256` keys go.

- [ ] **Step 1: Failing tests** (in `collect-review-evidence.test.py`; adapt the existing D10.6 tests, keep the
  FIFO, symlink, over-size and missing-file ones as they are):
  - the box file in the REWRITTEN layout above (with the other top-level keys) → `equals_repo: true`,
    `reason: "-"`, and `canonical_sha256` equal to the template's;
  - a fourth tool → `equals_repo: false`, `reason: "differs"`;
  - a second `mcp_servers` key spelled `"mcp\x5fservers":` at top level → `false`, `top_level_not_plain`;
  - a secret-looking value in `args` → not in the bundle (the existing assertion), `reason: "differs"`;
  - binary content → `false`, `unparseable`, no exception;
  - the template itself unreadable or without a block → the item is could-not-check.

- [ ] **Step 2: Implement.** In `d10_6`: read both files' text through `A.read_capped(path, MCP_CONFIG_CAP)`
  (decode `utf-8`, `errors="replace"`), a refusal or `OSError` → `CouldNotCheck` as today; call
  `mcp_config.compare(box_text, repo_text)`, a `ValueError` → `CouldNotCheck("config.yaml.example: no usable
  mcp_servers block")`. Remove `_mcp_block`, `_block_sha256` and `_MCP_KEY_RE`, and update `d10_6`'s
  docstring. The `gateway_mcp_list` part is unchanged.

- [ ] **Step 3: `CHECKLIST.md`.**
  - `version: 1.13`, and append to the history paragraph: `(v1.13: D10.6 compares the parsed MCP block, not
    its lines: the gateway rewrites data/config.yaml; every top-level key must be a plain name.)`
  - D10.6 **claim**: the box's `mcp_servers` configuration is, value for value, the committed one.
  - D10.6 **expected**: `mcp_block.equals_repo` is `true`, `reason` is `-`, and `canonical_sha256` is the
    committed block's value (compute it with `mcp_config` from `config.yaml.example` and write the hex).
    Explain in the item, in its existing voice: the gateway rewrites `data/config.yaml` (layout, quoting and
    key order may differ from the template), so the collector parses both blocks with a strict parser and
    compares the values; mapping key order does not matter, list order does. Every top-level key of the box
    file must be a plain name and `mcp_servers` must appear once, so a second key in another YAML spelling is
    `top_level_not_plain`, not a pass. Keep the sentences on `tools.include` as defence in depth, the broker
    as the boundary, and `gateway_mcp_list` as information reported under **Not on the checklist**. REMOVE the
    v1.12 sentences that state the line-based limit (escape, tag, anchor, complex key): that limit is gone.
  - D10.6 **pass rule**: `equals_repo: false` is a FAIL, whatever the `reason` (`no_block`, `duplicate_key`,
    `top_level_not_plain`, `unparseable`, `differs`); a `canonical_sha256` other than the stated value is a
    FAIL; could-not-check is CANNOT-VERIFY, as before.
- [ ] **Step 4: `security-review-checklist.test.py`.** The test that keeps the checklist's pinned D10.6 values
  equal to the template now pins `canonical_sha256` (computed with `mcp_config`) and no longer `lines`/`sha256`.
- [ ] **Step 5: `BRING-UP.md`**, part 2 step 6: one sentence after the `install` command: the gateway rewrites
  `data/config.yaml` once it runs (layout only); review item D10.6 compares the parsed `mcp_servers` block
  with the template, so do not re-install the template to "fix" a layout difference.
- [ ] **Step 6: Run** `infra/hermes-agent/bin/run-bin-tests.sh` (`54/54`),
  `python3 infra/hermes-agent/bin/security-review-checklist.test.py -v`,
  `python3 infra/hermes-agent/bin/check-checklist-version.py --base origin/main` (after committing: `raised
  1.12 -> 1.13`), `node scripts/run-all-tests.js`.
- [ ] **Step 7: Commit**

```bash
git add infra/hermes-agent/bin/collect-review-evidence.py infra/hermes-agent/bin/collect-review-evidence.test.py infra/hermes-agent/deploy/security-review/CHECKLIST.md infra/hermes-agent/bin/security-review-checklist.test.py infra/hermes-agent/deploy/BRING-UP.md
git commit -m "fix(hermes): D10.6 compares the parsed MCP block (the gateway rewrites config.yaml); checklist v1.13"
```

---

## Self-review notes (done while writing)

- **Coverage:** the healthy-box FAIL is Tasks 3–4; each Review Focus line has its test in Task 3 (parser) and
  the collector-level cases in Task 4.
- **Why a strict subset and not a YAML library:** the box has stdlib Python only, and running the gateway's
  own parser would mean trusting the reviewed party's interpreter with its own file.
- **What a reviewer loses:** nothing; `lines` and the raw `sha256` only described layout. What they gain:
  the "another spelling of the key" limit from v1.12 is closed by the plain-top-level rule.
- **If the gateway's writer changes layout again** (a future Hermes version): anything outside the subset is
  `unparseable`, a FAIL with a reason, never a silent pass; the subset is then extended deliberately.
- **Fingerprint:** `bin/` and `deploy/` are in the box fingerprint; pulled together with the MCP ping fix.
