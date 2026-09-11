# Agent Review Orchestrator V0.2 RC3 Remediation Specification

**Status:** Required before V0.2 final product validation
**Repository baseline:** `92c7dfd2eb6f6e425fe9b021abc8d9f169bd216b`
**Code baseline:** V0.2-RC2 `11bf2ef79f3c8dea4d50a7dc33f47541f103384f`
**Review status:** RC2 closes B201/B202/B203; independent post-RC2 review found one remaining Human Authority blocker (B301) and one local protocol-hardening item (N301).
**Scope:** Close the Human answer interpretation boundary only. Do not expand into V0.3 telemetry, seeded-phase E2E infrastructure, role routing, multi-reviewer, source implementation, or generic workflow changes.

---

## 1. Review conclusion

V0.2-RC2 correctly closes the three RC1 protocol blockers:

- FINAL_REVIEW now participates in Human Authority / Convergence routing;
- Problem Mode FACT convergence preserves decision semantics and can re-enter INVESTIGATE;
- Human Decision Candidate provenance, semantic category, option-key uniqueness, and decision-key identity are mechanically validated before Gate creation.

RC2 also adds a deterministic `handoff.md` fallback and clarifies that Agent-proposed options are suggestions rather than Human-approved decisions.

However, the RC2 validation boundary is still narrower than the actual CLI answering protocol.

RC2 proves that **option keys** are unique after normalization, but the Human can answer a Gate using more than an option key:

```text
number
option key
option label
key + label
```

The protocol also reserves control tokens such as:

```text
0 / custom / 自定义 / ...
都按推荐 / 按推荐 / ...
```

Therefore the true safety invariant is not:

> option keys are unique

but:

> every normalized Human input accepted as authoritative must have exactly one interpretation.

Until that invariant is mechanically enforced, Human Authority can still be silently mis-recorded.

V0.2 should therefore remain in RC status until B301 is closed.

---

## 2. Blocking finding

## B301 — Human Answer Alias Space is not mechanically unambiguous

### 2.1 Current behavior

`match_option()` currently accepts multiple aliases for each option. Conceptually, for option `i` it recognizes:

```text
option.key
option.label
option.key + " " + option.label
str(i)
"选项" + i
"option " + i
```

All values are normalized through the answer-normalization function before comparison.

Separately, `_ask_pass()` recognizes protocol-level commands before normal option matching, including:

```text
CUSTOM selectors:
0
custom
自定义
自定义决策
自己定义
自己决定

GLOBAL recommendation selectors:
都按推荐
按推荐
全部按推荐
all recommended
```

RC2 only guarantees uniqueness for normalized **option keys**.

That is insufficient because labels, composite aliases, numeric aliases, and protocol control tokens participate in the same Human input namespace.

### 2.2 Concrete ambiguity: duplicate labels

This packet is currently structurally valid:

```text
1. [keep]   保持现状
2. [legacy] 保持现状
```

The keys are unique, but the normalized label alias `保持现状` belongs to two options.

If the Human answers:

```text
保持现状
```

`match_option()` walks options in order and can silently select the first option.

That means:

```text
Human gives one valid CLI answer
→ answer has two valid semantic interpretations
→ Orchestrator silently chooses one
→ ACTIVE Human Decision is persisted
```

This violates Human Authority.

### 2.3 Concrete ambiguity: option alias vs numeric selector

Example:

```text
1. [safe] 安全修复
2. [1]    兼容修复
```

The second option key `1` conflicts with the first option's numeric selector `1`.

A Human typing `1` cannot be interpreted uniquely.

The same class applies to labels or composite aliases that normalize to:

```text
1
2
3
4
选项1
option 1
...
```

### 2.4 Concrete ambiguity: option alias vs protocol control token

Example:

```text
1. [normal] custom
2. [other]  其他方案
```

The key does not collide with the custom selector, but the label does.

Because custom-mode detection happens before option matching, Human input:

```text
custom
```

enters custom-decision mode instead of selecting the visible option.

The same problem exists for aliases colliding with global recommendation commands such as `按推荐`.

This produces a displayed option that is not safely selectable through all advertised answer forms.

### 2.5 Required invariant

For every persisted `GateQuestion`, construct the complete normalized **Human Answer Alias Space**.

For each option at 1-based index `i`, define its option-owned aliases from the exact forms the CLI accepts:

```text
normalize(option.key)
normalize(option.label)
normalize(option.key + " " + option.label)
normalize(str(i))
normalize("选项" + str(i))
normalize("option " + str(i))
```

It is acceptable for two aliases belonging to the **same option** to normalize to the same string.

It is NOT acceptable for aliases belonging to **different options** to intersect.

Formally:

```text
for every option A != option B:
    aliases(A) ∩ aliases(B) == ∅
```

Also define the normalized protocol-control namespace:

```text
CUSTOM_REQUEST_ANSWERS
GLOBAL_RECOMMEND_ANSWERS
```

No option-owned alias may intersect that namespace:

```text
for every option:
    aliases(option) ∩ protocol_control_aliases == ∅
```

The numeric custom selector `0` is included through the custom-control set.

### 2.6 Single source of truth

The same helper must drive both:

1. Gate validation; and
2. runtime option matching.

Do not create one alias implementation in the model validator and a separate hand-written alias implementation in `match_option()`.

Recommended conceptual API:

```text
normalized_option_aliases(question, option_index)
normalized_protocol_control_aliases()
```

or an equivalent pure helper.

Then:

```text
GateQuestion validation
→ prove alias sets are disjoint

match_option()
→ use the same alias sets to resolve input
```

This prevents validation and runtime interpretation from drifting apart in future versions.

### 2.7 Defense in depth

Even though a valid `GateQuestion` should make ambiguous matches impossible, runtime matching should not rely on "first match wins" as an authority rule.

Preferred behavior:

```text
0 matches → unmatched
1 match   → return that option
>1 match  → fail closed / treat as protocol ambiguity
```

An ambiguity should never silently become an ACTIVE Decision.

This protects against malformed/corrupt historical artifacts or future validator regressions.

The exact error surface may be implementation-defined, but it must not persist one of multiple possible Human meanings.

### 2.8 Scope of enforcement

Apply the invariant at the shared GateQuestion boundary so it protects:

- normal Intake Gates;
- Problem Mode FACT Gates;
- review-discovered Convergence Gates;
- future Gate producers that reuse the same model.

Convergence candidate validation may additionally reject earlier with a clearer handoff reason, but the shared model invariant remains authoritative.

Do not auto-rename Agent option keys or labels.

Do not silently remove conflicting options.

Invalid packets must be suppressed/rejected before the Human is asked.

---

## 3. Non-blocking protocol hardening

## N301 — Intake must reject option counts outside 2–4 instead of truncating

### Problem

The protocol requires every Human decision question to contain 2–4 meaningful options.

Convergence candidate validation already enforces:

```text
2 <= len(options) <= 4
```

But the normal Intake path currently checks only the lower bound and later constructs the question from:

```text
candidate.options[:4]
```

Therefore an Agent can emit five or more options and the host silently discards the extras.

This is problematic because:

- the Agent-visible packet and Human-visible packet differ;
- an Agent recommendation may point to a truncated option;
- silent truncation changes the proposed decision space without an explicit protocol decision.

### Required correction

Normal Intake candidate filtering must enforce the same 2–4 option rule as Convergence packets:

```text
len(options) < 2 → suppress/reject
len(options) > 4 → suppress/reject
```

Do not truncate to four.

`_to_question()` should consume the already validated option list rather than hiding invalid cardinality with slicing.

Prefer one reusable structural validation policy for all Gate producers where practical.

### Auditability

An Intake candidate rejected for option count must emit a deterministic suppression/audit reason, for example:

```text
requires 2-4 meaningful options, got 5
```

No Gate is created and no Human interruption is consumed for the malformed candidate.

---

## 4. Required RC3 deterministic regression suite

All existing V0/V0.1/V0.2/RC2 tests must remain green.

Add focused RC3 tests covering at least the following.

### B301 — cross-option ambiguity

1. Two options with different keys but the same normalized label are rejected.
2. Label aliases differing only by normalization are rejected.
3. A key alias of one option colliding with another option's label is rejected.
4. A composite `key + label` alias colliding with another option alias is rejected.
5. An option key/label/composite alias colliding with another option's numeric index alias is rejected.
6. Collision with `选项N` / `option N` aliases is rejected.

### B301 — protocol-control ambiguity

7. Any option alias colliding with `0` or a custom selector is rejected.
8. Any option alias colliding with a global-recommend selector is rejected.
9. Collision checks use the exact same normalization as runtime answer matching.

### B301 — valid behavior preserved

10. A normal packet with distinct aliases remains valid.
11. Numeric answer selects the intended option.
12. Key answer selects the intended option.
13. Label answer selects the intended option.
14. `key + label` answer selects the intended option.
15. Custom selectors still enter custom mode.
16. Global recommendation selectors still preserve existing behavior.

### B301 — defense in depth

17. Runtime matching cannot silently choose the first option if more than one interpretation somehow exists; ambiguity fails closed / remains unresolved and never creates a Decision.

### N301 — cardinality

18. Intake candidate with one option is suppressed/rejected as before.
19. Intake candidate with five options is suppressed/rejected; no truncation.
20. Exactly two options works.
21. Exactly four options works.
22. Malformed cardinality creates no Gate and consumes no Human interruption.
23. Suppression reason is auditable.

### Preservation

24. Custom Human Decision regressions remain green.
25. PROD-001 permanent replay remains green.
26. RC2 FINAL_REVIEW convergence regressions remain green.
27. RC2 Problem FACT reinvestigation regressions remain green.
28. RC2 candidate provenance/identity regressions remain green.
29. Gate current/history/Markdown consistency remains green.
30. V0.1 runtime/session presentation remains green.

---

## 5. Validation Budget — mandatory RC3 execution constraint

RC2 exposed a process failure: attempting to force two low-probability real-agent routing hops consumed roughly four hours across many fresh sessions without hitting the target branches.

RC3 must not repeat that validation pattern.

This is a protocol-boundary repair whose correctness can be exercised deterministically. Real-agent validation is supplemental, not a reason to perform unbounded probabilistic search.

### Hard validation budget

For RC3 implementation, the autonomous implementation agent must obey:

```text
maximum fresh real-agent E2E sessions for RC3-specific behavior: 2
maximum request variants used only to force a branch: 2
maximum total wall-clock spent on RC3 real-agent E2E forcing: 60 minutes
```

Whichever limit is reached first ends branch-forcing attempts.

Do not start another real session merely because a probabilistic Agent failed to emit the desired malformed/edge packet.

### Required validation evidence

RC3 requires:

1. full deterministic suite green;
2. focused RC3 deterministic regressions green;
3. real Pi/Codex adapter smoke green when available.

A fresh full real E2E is **not required** to prove B301/N301, because malformed alias/cardinality packets should be created as deterministic fixtures, not waited for from a probabilistic Agent.

If a real run naturally exercises the updated Gate boundary within the validation budget, record it as supplemental evidence.

If it does not, report that honestly and stop.

### Future seeded-phase E2E

A seeded-phase + real-adapter continuation mode remains a useful future direction for validating rare routing hops cheaply, but it is outside RC3 scope.

Do not implement it as part of this remediation.

---

## 6. Non-goals

RC3 must not change:

- Human interruption budget defaults;
- Revision / Ablation budgets;
- mechanical PASS;
- issue lifecycle ownership;
- Human Authority Check semantics;
- FINAL_REVIEW convergence routing added in RC2;
- Problem Mode FACT reinvestigation semantics added in RC2;
- task revision invalidation;
- terminal handoff resumability policy;
- V0.3 telemetry design;
- agent role/routing architecture;
- source-code implementation/deployment behavior.

This is a small Host protocol-boundary hardening release.

---

## 7. RC3 exit criteria

RC3 is complete only when all of the following are true:

1. Every accepted Human answer string has exactly one authoritative interpretation within its Gate question.
2. Cross-option alias collisions fail before Human interaction.
3. Option aliases cannot collide with custom or global-recommend protocol commands.
4. Runtime matching never uses silent first-match-wins when multiple interpretations exist.
5. Validation and runtime matching share one alias-definition source of truth.
6. Intake no longer truncates >4 options.
7. Malformed alias/cardinality packets create no Gate and consume no Human interruption.
8. Existing Custom Decision behavior is unchanged.
9. RC2 B201/B202/B203 regression suites remain green.
10. Full deterministic suite passes without V0/V0.1/V0.2 regression.
11. Real Pi/Codex smoke is healthy when available.
12. RC3 validation obeys the explicit Validation Budget and does not perform unbounded probabilistic E2E branch forcing.

After these criteria pass, perform a focused code review of B301/N301 only. If no new blocker is found, return to normal real Shopify usage for product validation rather than creating another synthetic RC solely to force rare Agent behavior.
