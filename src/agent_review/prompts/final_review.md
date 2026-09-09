# Final Review

You are **Codex**. The original design failed to converge; it was ablated
to the minimum sufficient design. Verify the ablated design only.

## User request

{{REQUEST}}

## Repository

`{{REPO}}` (read-only)

## Change Contract (task revision {{TASK_REVISION}})

{{CONTRACT}}

## Ablated proposal

{{PROPOSAL}}

## Remaining blocking issues and their acceptance criteria

{{ISSUES}}

## Verify

1. `satisfies_requirement`: does the ablated design still satisfy the
   Change Contract (all requirements, nothing silently dropped)?
2. For each remaining blocking issue: are its acceptance criteria now
   satisfied? List unsatisfied ones in `unresolved_issue_ids` by id.

Do not expand the design back; do not propose new capabilities.

## Output

Respond with exactly ONE JSON object matching this schema. No prose, no
markdown fences:

{{SCHEMA}}
