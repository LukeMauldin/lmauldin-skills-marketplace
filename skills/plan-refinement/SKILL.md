---
name: plan-refinement
description: Refine one or more draft implementation plans into a tighter execution-ready plan. Use when the user has a handoff doc, discovery brief, repo context, or multiple competing plans and wants critique, pruning, comparison, synthesis, and a revised plan without blindly preserving seed assumptions.
---

# Plan Refinement

Use this skill when the job is to improve planning inputs, not to implement. This skill is for "first draft plus refine" and "compare or merge multiple plans with refinement" workflows.

## Announce Skill Usage

Before starting substantive work, say: "I'm using the plan-refinement skill to audit the draft plan inputs and produce a tighter execution-ready plan."

## Core Behavior

- Treat authoritative sources as higher priority than any seed plan. Typical authority order:
  - explicit user instructions
  - handoff docs, discovery briefs, or decision logs the user designates as source of truth
  - repo evidence
  - seed plans
- Treat every draft plan as a proposal to critique, not a script to preserve.
- Remove wrong assumptions, narrow over-scoped work, and add missing implementation-critical detail.
- Resolve repo-checkable ambiguities yourself before asking questions.
- Ask questions only when blocked by a real stakeholder or product decision.
- Produce a refined plan that is ready to hand to an implementation model or engineer.

## When To Use This Skill

Use this skill when one of these is true:

- The user has a handoff doc and one seed plan that needs tightening.
- The user has multiple plans from different models and wants a best-of synthesis.
- The user wants to compare plan quality before choosing a plan to implement.
- The user wants to preserve speed by using a fast draft plan and then having a stronger model critique and refine it.

Do not use this skill for initial scoping when the problem itself is still unclear. Use `scout-task` first for that.

## Refinement Modes

Classify the task into one of these modes before refining:

- Single-seed refinement: one draft plan plus one or more authoritative sources.
- Multi-plan synthesis: two or more competing plans plus one or more authoritative sources.
- Plan quality review: the user primarily wants evaluation, ranking, or "good enough" judgment, even if you also propose a refined plan.

Pick the lightest mode that fits the request.

## Workflow

### 1. Establish the source of truth

- Identify the authoritative inputs.
- State what is binding versus advisory.
- If the user supplied multiple plans, state that none of them are authoritative unless the user says otherwise.

### 2. Audit the inputs

- Read the source-of-truth doc or brief first.
- Read the seed plan or plans.
- Check the repo only where it can settle disputed assumptions, missing interfaces, affected file clusters, or risky sequencing.
- Mark each important plan assumption as one of:
  - supported by the source of truth
  - contradicted by the source of truth or repo
  - plausible but unresolved
  - irrelevant or over-scoped

### 3. Decide what to keep, drop, and add

- Keep useful structure and sequencing only when it still fits the source of truth.
- Drop steps that create extra refactors, cleanup waves, or speculative work outside the requested scope.
- Add missing decisions, compatibility constraints, file clusters, rollout notes, or edge cases that an implementation model would otherwise have to rediscover.
- If multiple plans complement each other, synthesize them rather than choosing one wholesale.

### 4. Tighten for execution

- Rewrite the plan into the smallest implementation-ready version.
- Prefer explicit phases, ownership boundaries, and constraints over long rationale sections.
- Call out non-goals so an implementer does not expand scope.
- State which open questions still require stakeholder input versus implementer judgment.

### 5. Return a refinement package

- Use the template in `references/refined-plan-template.md`.
- In multi-plan mode, also include a brief comparison table or scorecard before the final plan.
- If the plans are all weak, say so directly and produce a fresh refined plan from the source of truth instead of forcing a bad merge.

## Output Requirements

For single-seed refinement, return:

1. Source of Truth
2. Seed Plan Assessment
3. Rejected or Pruned Items
4. Added or Clarified Items
5. Refined Plan
6. Open Questions
7. Implementation Model Fit

For multi-plan synthesis, return:

1. Source of Truth
2. Plan Comparison
3. Best Elements Kept
4. Rejected Assumptions or Over-scope
5. Refined Plan
6. Open Questions
7. Implementation Model Fit

## Quality Bar

- Do not anchor on the most detailed plan just because it is longer.
- Do not anchor on the fastest plan just because it is cheaper or quicker.
- Prefer a narrower, correct plan over a comprehensive but speculative one.
- When you reject a seed-plan assumption, name it explicitly.
- Keep the refined plan implementation-facing. It should reduce execution-time rediscovery.
- If a plan is already good enough, say so and limit refinement to the real gaps.

## Implementation Model Fit

End by stating what class of implementer the refined plan is suitable for:

- Senior engineer directly
- Strong frontier coding model with low or medium effort
- Mid-tier coding model that still needs a stronger plan
- Not ready for implementation yet

State why. Focus on remaining ambiguity, cross-boundary reasoning, and risk of wrong first-pass execution.
