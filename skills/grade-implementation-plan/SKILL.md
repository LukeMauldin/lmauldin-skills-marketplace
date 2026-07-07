---
name: grade-implementation-plan
description: Grade one or more implementation/execution plans (ExecPlans, handoff plans, design docs) on substance and implementability, producing a weighted scorecard, letter grade, and ranking. Use when asked to grade, score, rank, or assess the quality of implementation plans — especially comparing competing drafts. Weights overall quality and "can a competent implementer execute this end-to-end" over format; caps the penalty for isolated, review-catchable errors so one wrong finding does not tank an otherwise strong plan.
---

# Grade Implementation Plan

Score implementation plans on whether they will produce a correct, working result when handed to an implementer — not on prose style or template conformance.

## When to use

- The user asks to grade / score / rank / assess one or more implementation plans, ExecPlans, handoff docs, or design docs.
- Comparing competing drafts (e.g., outputs from different models) to pick a base.
- Sanity-checking a plan before committing to implementation.

Not for grading finished code (use a code review), and not for grading prose/writing quality on its own.

## Core principle

Grade the plan as an instrument of execution. The question is always: **if a competent implementer (a strong coding model or a senior engineer) followed this plan, how likely is a correct, complete, working result with minimal rediscovery and minimal wrong turns?**

Two explicit biases, applied every time:

1. **Substance over format.** Do not reward or penalize template adherence, heading structure, fenced-vs-indented code, table-vs-prose, diagrams, or living-document sections — unless a format problem actively impairs comprehension or executability. A correct, executable plan in ugly formatting outranks a beautiful plan that is vague or wrong.
2. **Bounded penalty for catchable errors.** A single significant-but-catchable wrong finding is a bounded deduction, not a cascading failure. See "Error severity" — classify each error before scoring, and never let one error bleed across multiple dimensions.

## Dimensions and weights (100 points)

Score each dimension on its own 0–100 scale, then multiply by its weight to get weighted points.

- **Implementability & self-containment — 25.** Could the implementer execute end-to-end with little rediscovery? Concrete file paths, signatures, ordered build sequence, exact commands, named edits. Is it self-contained (no "see the other doc")? Is each step unambiguous? Clarity/organization counts here only insofar as it affects execution.
- **Completeness & scope coverage — 20.** Does it cover the full required scope and the right non-goals? Are dependencies, config, edge cases, env, and follow-ups addressed? Is anything load-bearing missing that the implementer would have to invent?
- **Technical correctness & soundness — 20.** Are the design decisions, signatures, data flows, queries, and tooling claims actually right? (Apply the error-severity rule here; this is where bounded deductions land.)
- **Risk identification & handling — 15.** Does it surface the real risks (and not invent fake ones), provide idempotence/recovery, sequencing safety, and rollback? Good scope judgment (deferring genuinely risky work) is rewarded here.
- **Verification & acceptance quality — 12.** Are acceptance criteria observable/behavioral (not "code was added")? Are tests specified concretely? Is "does it actually work" provable?
- **Fidelity to source of truth — 8.** Does it correctly consume the authoritative inputs (handoff, repo, requirements) — mirror existing behavior, reuse existing artifacts, respect stated constraints — rather than drift or recreate?

Total weighted points → letter band:

- 90–100 A (ready to implement as-is or as the base)
- 80–89 B (strong; minor fixes before implementation)
- 70–79 C (usable but needs real tightening or has a notable gap)
- 60–69 D (significant rework needed)
- < 60 F (not ready; rebuild from source of truth)

## Error severity (apply before scoring Correctness)

Classify every substantive error along three axes — **blast radius** (does it break the core, or one bounded part?), **catchability** (would standard review / a first test run surface it?), and **propagation** (does it silently corrupt downstream work?). Then bucket:

- **Catastrophic** — breaks the core design, OR is uncatchable AND propagates silently. Large deduction; may cap the whole Correctness score.
- **Significant–catchable** — a real wrong finding, but standard review or the first run would catch it, and it does not break the core architecture (it's localized to one milestone/decision). **Bounded deduction (cap ~one third of the Correctness dimension), and do NOT cascade it into Implementability/Completeness/Risk.** This is the case the user most often cares about: one wrong call in an otherwise strong plan.
- **Subtle–survives-review** — wrong but plausible, passes tests/review easily (e.g., an over-filter the fixtures happen to mask). Moderate deduction — slightly harsher than significant–catchable precisely because review will *not* save the implementer.
- **Minor** — cosmetic, over-engineering, or a small inaccuracy with no execution impact. Small deduction.

A plan that *correctly identifies and handles* a hard risk earns credit in Risk even if a different error exists elsewhere. Keep dimensions independent.

## Procedure

1. Identify the source of truth (handoff/requirements/repo) so "correctness" and "fidelity" are measured against something real. Verify disputed technical claims against the repo/primary sources where feasible — don't grade correctness from vibes.
2. Read each plan fully.
3. For each plan, list its substantive errors and classify each by severity (above).
4. Score each dimension 0–100 with a one-line justification; apply bounded penalties.
5. Compute weighted totals and letter grades.
6. Produce the output below.

## Output format

- A scorecard table: rows = plans, columns = the six dimensions (raw 0–100) + weighted total + letter.
- Per-plan narrative: top strengths, the classified errors (with severity), and the single most important fix.
- A ranking with a one-sentence "why this order."
- A recommendation: which plan to implement or use as the base, and what to graft from the others.
- State the implementer class each plan is suitable for, and your confidence in the grades (and what would change them).
