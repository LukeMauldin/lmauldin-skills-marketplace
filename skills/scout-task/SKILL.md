---
name: scout-task
description: "Investigate underdefined engineering or PM work such as tickets, issues, threads, repos, docs, logs, or PRs. Explore evidence, contradictions, risks, and key questions to produce a structured discovery brief before planning or implementation."
---

# Scout Task

Use this skill when the goal is to investigate and tighten scope, not to implement. Default to read-only exploration. Do not update tickets, docs, or code unless the user explicitly asks after the first pass.

## Announce Skill Usage

Before starting substantive work, say: "I'm using the scout-task skill to investigate the problem space and tighten the scope."

## Core Behavior

- Start from the user's stated direction, but treat the ticket or Slack summary as a hypothesis, not ground truth.
- Use the evidence the user supplied or explicitly pointed to. Expand outward only when another source is clearly required to validate or refute a claim.
- Stop and ask clarification questions only when ambiguity materially blocks progress. If the evidence can likely answer the question, investigate first.
- Return a structured discovery brief in the response. Keep any ticket or doc rewrite suggestions in the response unless the user explicitly asks you to apply them.
- Feed planning. Do not quietly drift into implementation or a full implementation plan.
- When the investigation is likely to feed multiple living artifacts, optimize for canonical decision capture and low-consistency overhead, not just completeness.
- For planning-heavy work, prepare a planning packet strong enough to bootstrap planning, but stop short of generating the plan itself.

## Evidence Rules

- Treat these as first-class evidence when the user provides them or points to them: tickets, Slack snippets, repos, sibling repos, PRs, docs, logs, metrics, dashboards, and incident notes.
- Prefer primary evidence over recollection.
- Keep a clean separation between facts, inferences, and open questions.
- Call out contradictions directly, especially when ticket language, code, and observed behavior do not line up.
- Avoid broad fishing expeditions. Do not inspect every possible system unless the user directed that or the local evidence clearly demands it.

## Clarification Threshold

Ask 2-5 high-leverage clarification questions when one of these is true:

- Multiple incompatible goals are plausible.
- Required repos, systems, or evidence sources are unknown.
- Business rules appear to drive the answer and are not recoverable from code or docs.
- Contradictions in the evidence materially change the likely scope and cannot be resolved locally.

If those conditions are not met, keep investigating and ask only the residual questions that remain after the first pass.

## Investigation Classification

Before drafting the brief, classify the task into one of these modes:

- Standard scout: bug scoping, dependency mapping, root-cause discovery, contract clarification, or rollout preparation where the discovery output is likely to become one planning artifact or one ticket update.
- Doc-preplanning scout: design exploration, contract-boundary work, architecture discovery, or phased implementation prep where the discovery output is likely to feed multiple downstream artifacts such as design notes, implementation handoffs, phase plans, ADRs, or ticket rewrites.

Use the standard scout output unless the evidence clearly points to doc-preplanning. Do not force the heavier format onto normal scoping work.

Doc-preplanning mode is appropriate when the likely downstream work includes one or more of these:

- a handoff doc plus a plan
- multiple design notes or implementation phases
- ADRs, ticket rewrites, or rollout notes that will restate the same concepts
- architecture or contract work where the planner will need settled decisions, recommended defaults, and file clusters rather than just a list of relevant paths

## Scout Workflow

### 1. Frame the request

- Restate the task in operational terms, not just ticket wording.
- Identify the likely work type: bug scoping, design exploration, dependency mapping, root-cause discovery, contract clarification, rollout preparation, or doc-preplanning / design-doc shaping.
- List the repos, services, APIs, teams, or artifacts that appear in scope.
- Decide whether the result is likely to stay as one brief or fan out into multiple living artifacts. If fan-out is likely, switch to doc-preplanning mode.

### 2. Build an evidence map

- List the evidence already provided.
- Identify the minimum additional sources needed for a credible first pass.
- Decide what to inspect first and why.
- In doc-preplanning mode, identify the likely decision-bearing sources and the concepts most likely to drift if copied into multiple docs.
- If planning is the next step, identify which repo facts can be resolved now so the planner does not waste time rediscovering them later.

### 3. Investigate

- Read the code paths, interfaces, docs, tickets, logs, or messages required to understand current behavior.
- Follow references one hop at a time.
- Surface where the task is underspecified, inaccurate, or mixing multiple concerns.
- Distinguish symptom, mechanism, and probable root cause.

### 4. Tighten the scope

- Define the real problem being solved.
- Identify affected systems, interfaces, data boundaries, and ownership.
- Propose 1-3 viable scope shapes or solution directions with tradeoffs.
- Say when the work should be split into multiple tickets or when a separate design note is warranted.
- In doc-preplanning mode, also decide the artifact topology:
  - whether the output should remain a single canonical brief
  - whether multiple downstream artifacts are warranted
  - which artifact should be the source of truth for decisions, invariants, and open questions
  - which information should be linked or derived rather than duplicated
  - whether the likely planner will still need to make architecture decisions or should primarily execute against settled ones

### 5. Prepare handoff

- Produce a structured discovery brief using the template in `references/discovery-brief-template.md`.
- Include concrete next actions, open questions, and what is still needed before a planning LLM should take over.
- If useful, draft suggested ticket, doc, or handoff text, but do not apply it unless asked.
- In doc-preplanning mode, include:
  - a decision ledger split into settled decisions, working decisions, and open questions
  - recommended defaults for any open decisions that the planner will likely need to resolve
  - a short list of volatile concepts or terms that are likely to require coordinated edits later
  - an artifact strategy that names the canonical source for each volatile area
  - an explicit consistency-risk callout when multiple docs are recommended
  - a planning packet that names likely file clusters, interfaces, constraints, and explicit "avoid" guidance for the planner

## Output Requirements

Default to a concise discovery brief with these sections:

1. Objective
2. Evidence Reviewed
3. Current Behavior / Observed Problem
4. Likely Root Cause or Design Gap
5. Impact / Affected Systems
6. Scope Options
7. Recommended Scope
8. Open Questions
9. Risks / Dependencies
10. Planning Handoff Notes

Each section should be evidence-backed. If confidence is low, say what evidence would change the conclusion.

For doc-preplanning mode, expand the brief to include:

11. Key Decisions / Invariants
12. Volatile Concepts / Terms
13. Artifact Strategy
14. Consistency Risks
15. Planning Packet

Use these only when the investigation is likely to produce multiple downstream artifacts or repeated design references.

## Quality Bar

- Do not merely summarize the ticket.
- Challenge weak assumptions directly.
- Prefer concrete file, API, queue, table, service, and repo names over abstract labels.
- Name the deciding evidence behind each recommendation.
- Keep the result useful to both engineering and PM audiences.
- If the task is already well-defined, say so explicitly and explain what is already ready for planning.
- In doc-preplanning mode, do not recommend multiple docs unless you also explain how decision drift will be contained.
- Prefer one canonical decision-bearing artifact over multiple peer documents when the same concepts would otherwise need to be maintained in parallel.
- Prefer planning packets that reduce planner rediscovery: settled decisions, recommended defaults, relevant file clusters, explicit constraints, and explicit non-goals.

## After the Initial Scout Pass

If the user asks to continue beyond read-only discovery:

- For ticket updates: draft or apply tighter problem statements, scope notes, acceptance criteria, and follow-up questions.
- For docs: convert the brief into a design note, implementation handoff, or decision record. In doc-preplanning mode, preserve the canonical decision ledger and derive narrower views from it instead of duplicating decisions across peer docs.
- For handoff to another LLM: compress the output into a planning packet with problem statement, evidence, constraints, recommended scope, unresolved questions, canonical decision / artifact-topology guidance, likely file clusters, and recommended defaults for still-open choices.
