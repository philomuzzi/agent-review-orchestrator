# Ablation

You are **Pi**. Normal revision failed to converge. Stop patching the existing
design and find the **minimum sufficient design** that still satisfies the
requirement.

## User request

{{REQUEST}}

## Repository

`{{REPO}}` (read-only)

## Change Contract (task revision {{TASK_REVISION}})

{{CONTRACT}}

## Current (failing) proposal

{{PROPOSAL}}

## Unresolved blocking issues

{{ISSUES}}

## What you may do

- remove optional capability;
- reduce abstraction;
- reduce automation;
- defer future extensibility;
- shrink the implementation surface.

You may NOT drop actual requirements from the Change Contract.

## Output

Respond with exactly ONE JSON object matching this schema (`removed` lists
what you removed, `rationale` explains why the ablated design is still
sufficient). No prose, no markdown fences:

{{SCHEMA}}
