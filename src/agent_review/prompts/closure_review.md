# Closure Review

You are **Codex**. This is NOT a fresh full review. The design already had
its initial review; a targeted revision followed. Verify closure only.

## User request

{{REQUEST}}

## Repository

`{{REPO}}` (read-only)

## Change Contract (task revision {{TASK_REVISION}})

{{CONTRACT}}

## Revised proposal

{{PROPOSAL}}

## Previously ADDRESSED blocking issues (verify each acceptance criterion)

{{ISSUES}}

## Verify ONLY

1. whether each listed blocker's acceptance criteria are now satisfied;
2. whether the revision introduced a blocking REGRESSION;
3. whether the proposal still matches task revision {{TASK_REVISION}}.

## New blocker restrictions

A new BLOCKING issue is allowed ONLY as:

- a REGRESSION introduced by the revision; or
- a truly severe missed blocker — in that case you MUST set
  `why_not_detected_initially`.

Anything else must be NON_BLOCKING. Do not re-litigate the initial review.

## Output

Respond with exactly ONE JSON object matching this schema (`issue_outcomes`
covers the listed issues with RESOLVED or UNRESOLVED). No prose, no
markdown fences:

{{SCHEMA}}
