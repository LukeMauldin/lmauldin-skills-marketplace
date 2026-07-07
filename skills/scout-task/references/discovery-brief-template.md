# Discovery Brief Template

Use this structure unless the user asks for a different format.

## Objective

State the real task in one short paragraph. Prefer an operational problem statement over ticket wording.

## Evidence Reviewed

- List each first-class source inspected.
- Note the most important files, docs, messages, logs, or tickets.
- Call out any evidence you expected but could not inspect.

## Current Behavior / Observed Problem

Describe what the system appears to do today and what symptom or failure matters.

## Likely Root Cause or Design Gap

Separate confirmed facts from inference. If multiple explanations remain plausible, list them in likelihood order.

## Impact / Affected Systems

Name the users, services, repos, interfaces, data sources, or teams affected.

## Key Decisions / Invariants

- Use this section when the investigation is feeding planning, design notes, or multiple downstream artifacts.
- Split into:
  - Settled decisions: evidence-backed decisions that planning should treat as fixed unless new evidence appears.
  - Working decisions: current operating assumptions that may still change.
  - Invariants: boundaries or rules that any viable option must preserve.
- If the task is not decision-heavy, keep this section brief or omit it.

## Volatile Concepts / Terms

- List the concepts, terms, identities, or boundaries that are likely to drift if copied into multiple docs.
- For each one, say why it is volatile and which source should define it canonically.
- Examples: ownership terms, source-of-truth statements, state-machine semantics, identifier strategy, vendor scope boundaries.

## Scope Options

Present 1-3 viable options. For each option, include:

- What changes
- What it avoids changing
- Main upside
- Main risk or limitation

## Recommended Scope

Recommend the narrowest scope that credibly addresses the problem. State why that scope is preferable now.

## Artifact Strategy

- State whether the output should remain one canonical brief or split into multiple downstream artifacts.
- If split is recommended, name each artifact and its responsibility.
- Explicitly identify:
  - which artifact is the source of truth for decisions and invariants
  - which artifact is the source of truth for execution sequencing
  - what should be linked or derived instead of duplicated
- If no split is needed, say that directly.

## Open Questions

List only the questions that still materially affect scope or planning.

## Risks / Dependencies

Call out cross-team dependencies, contract changes, data quality concerns, rollout risks, or missing evidence.

## Consistency Risks

- Use this section when multiple downstream docs or tickets are likely.
- Call out where the same concept would otherwise need to be edited in parallel.
- If the consistency burden is high, say how to reduce it: one canonical ledger, generated summaries, narrower artifact boundaries, or fewer living docs.

## Planning Packet

- Use this section when the next likely step is formal planning.
- Include:
  - likely file clusters or systems the planner should inspect first
  - interfaces, contracts, or schemas that constrain the plan
  - explicit non-goals or "avoid" guidance
  - recommended defaults for open decisions when the scout evidence strongly points one way
  - residual questions that truly require planner judgment or stakeholder input
- Keep this section short and operational. It should help a planner start with fewer discovery loops, not become the plan itself.

## Planning Handoff Notes

Describe what a planning or implementation LLM should receive next. Include likely repos, interfaces, constraints, canonical decisions, artifact-topology guidance, and any suggested ticket or doc follow-up.
