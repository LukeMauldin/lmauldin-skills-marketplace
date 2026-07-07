# Software Plan Checklist

Use this reference when merging two plans for a software feature, system change, migration, or medium-sized implementation effort.

## What Good Looks Like

A strong merged plan:

- aligns to the real objective rather than to either model's wording
- captures architecture and interface consequences, not just coding steps
- sequences work in a way that reduces rework and integration risk
- includes validation, rollout, and rollback where those matter
- makes assumptions and unresolved questions explicit

## Review Categories

Check each plan and the merged result against these categories.

### 1. Objective and Scope

- Is the user-visible goal stated clearly?
- Are non-goals or out-of-scope items identified?
- Does the plan solve the actual request, or an adjacent interpretation?

### 2. Current-State Discovery

- Does the plan require reading existing code, schemas, contracts, or operational setup first?
- Does either plan assume new abstractions without checking existing patterns?
- Are there repo-local conventions that should constrain the design?

### 3. Architecture and Boundaries

- Are ownership boundaries clear across services, packages, modules, and APIs?
- Does the plan respect existing layering and architectural constraints?
- Are integration points, contracts, and compatibility implications called out?

### 4. Data and State Changes

- Are schema, persistence, caching, or event changes required?
- Are migrations, backfills, dual-write periods, or cleanup tasks missing?
- Are idempotency, consistency, and failure modes considered?

### 5. Dependency Ordering

- Are prerequisites explicit?
- Can workstreams run in parallel safely?
- Does the sequencing avoid dead ends and repeated churn?

### 6. Testing and Verification

- Are unit, integration, end-to-end, or contract tests identified where appropriate?
- Does the plan specify how correctness will be verified beyond "run tests"?
- Are observability checks or manual QA steps needed?

### 7. Rollout and Operations

- Does the change need feature flags, staged rollout, monitoring, or alert updates?
- Is rollback or mitigation addressed for risky changes?
- Are operational ownership and post-deploy checks defined?

### 8. Risks and Unknowns

- Are the hardest assumptions surfaced explicitly?
- Does either plan ignore high-risk dependencies or external systems?
- Are open questions truly blocking, or can the plan proceed with stated assumptions?

## Merge Heuristics

Apply these rules when synthesizing the final plan.

1. Start from the stronger plan shape.
   - Usually this is `primary`, unless its structure hides important work or forces a weak sequence.

2. Import unique value from `alt`, not just wording.
   - Prefer additions such as hidden dependencies, safer sequencing, migration steps, validation strategy, and operational concerns.

3. Collapse overlapping steps.
   - Do not keep duplicate phases that only differ in wording.

4. Replace weak assumptions with checked assumptions.
   - If either plan assumes an interface, schema, or pattern, verify it against local evidence when available.

5. Turn critiques into actions.
   - If `alt` points out a risk, the merged plan should add an explicit mitigation, validation step, or decision point.

6. Keep unresolved items visible.
   - Do not fake certainty. If a decision depends on missing information, mark it as an open question or discovery task.

## Research Triggers

Do extra exploration before finalizing the plan when:

- the two plans disagree on existing architecture or system behavior
- one plan proposes a migration, rollout, or compatibility step and the other ignores it
- external interfaces, vendor behavior, or framework constraints may have changed
- the plan depends on current repository structure or patterns that can be inspected locally

## Suggested Final Plan Sections

Adapt these to the shape of `primary` unless a better structure is clearly needed.

- Recommendation or summary
- Workstreams or phases
- Dependencies and sequencing notes
- Testing and validation
- Rollout or operational considerations
- Risks and open questions
