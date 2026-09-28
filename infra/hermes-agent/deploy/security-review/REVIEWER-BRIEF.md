# Brief for the independent security reviewer

You are reviewing a production box you did not build. You receive ONLY:

1. `CHECKLIST.md` (this directory) — cite its `version:`.
2. The box bundle and the laptop bundle (JSON, redacted by design).
3. `docs/superpowers/specs/2026-09-21-vps-first-bring-up-findings.md`.

You do not receive the build conversation. Do not ask for it.

## Rules

- Judge every checklist item: `PASS`, `FAIL` or `CANNOT-VERIFY`. Quote the evidence (a short excerpt) for each.
- `could-not-check` evidence is `CANNOT-VERIFY`. Missing evidence is `CANNOT-VERIFY`. Never pass by default — ask the operator for more evidence instead.
- Anything alarming the checklist does not cover goes in **Not on the checklist**, with your recommendation.
- For D3.2 you may recommend a dedicated STANDARD-access account; the operator decides.
- The overall verdict is PASS only if every item is PASS (manual items: the operator's statement is the evidence).
- Never paste a client slug, a customer id or a credential value into the report — the bundles already hide them; keep it that way.

## Output

Write `docs/security-reviews/YYYY-MM-DD-review.md` from `REPORT-TEMPLATE.md`.
