# Refined Plan Template

Use this structure unless the user asks for a different format.

## Source of Truth

- Name the binding inputs.
- Name any advisory inputs.
- State what the refined plan is optimizing for: correctness, speed, narrow scope, lowest-risk rollout, or another explicit user priority.

## Seed Plan Assessment

- Use this section for single-seed refinement.
- Summarize what the seed gets right.
- Name the main weaknesses directly: wrong assumptions, under-specification, over-scope, or missing edge cases.

## Plan Comparison

- Use this section for multi-plan synthesis.
- Compare the plans on:
  - scope control
  - correctness against the source of truth
  - execution readiness
  - likely implementation risk
  - speed or cost tradeoffs when relevant
- Keep the comparison short and decision-oriented.

## Best Elements Kept

- Use this section when refining from multiple plans.
- List the useful pieces you are carrying forward and why.

## Rejected or Pruned Items

- List the assumptions, phases, or tasks you are removing.
- Say why each item was rejected: contradicted, over-scoped, duplicative, speculative, or not needed yet.

## Added or Clarified Items

- List what the refined plan adds that an implementer would otherwise have to rediscover.
- Examples: interfaces, file clusters, compatibility constraints, sequencing dependencies, stable identity rules, rollout constraints, explicit non-goals.

## Refined Plan

- Present the final implementation-ready plan.
- Prefer short numbered phases or workstreams.
- Keep each step concrete:
  - what changes
  - where it likely changes
  - why it exists
  - what it explicitly avoids changing when that matters

## Open Questions

- List only the questions that still need stakeholder input or materially affect the plan.
- If no blocking questions remain, say that directly.

## Implementation Model Fit

- State which class of implementer can likely execute this plan safely:
  - senior engineer directly
  - strong frontier coding model
  - mid-tier coding model
  - not ready
- Explain the limiting factors briefly.
