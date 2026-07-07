---
name: merge-llm-outputs
description: "Use when given a primary LLM output plus an alternative response, plan, analysis, or draft. Mine the alternative for useful insights, missed risks, conflicts, and structure; verify factual disagreements, ask only blocking questions, and produce a revised synthesis."
---

# Merge LLM Outputs

## Goal

- Improve a primary answer by treating an alternative answer as a useful but fallible source of evidence.
- Produce a revised synthesis, not a superficial compromise and not a winner-only judgment.
- Preserve the shape of the primary answer by default. Change the structure only when the primary structure is actively limiting correctness or usefulness.

## Recommended Inputs

Prefer explicit tags when the user provides both outputs:

```xml
<prompt>
Original user request or task.
</prompt>

<primary>
The current best answer or preferred draft.
</primary>

<alt>
The alternative answer to mine for improvements and disagreements.
</alt>

<context>
Optional repo, files, constraints, prior decisions, or source materials.
</context>

<constraints>
Optional formatting, deadlines, audience, or non-goals.
</constraints>
```

If the user does not provide tags, infer the same roles from the message.

## Core Stance

- Treat `primary` as the baseline deliverable, not as unquestioned truth.
- Treat `alt` as evidence, not as authority.
- Separate ideas from claims. It is often correct to borrow the alternative's framing, risks, decomposition, or questions without borrowing its unsupported facts.
- Do not average two conflicting answers. Resolve conflicts against source material whenever possible.
- For engineering tasks, prefer independent verification through repo inspection, existing docs, tests, interfaces, and targeted external research when facts are unstable.
- Ask follow-up questions only when ambiguity materially affects scope, architecture, sequencing, or acceptance criteria.

## Workflow

1. Normalize the task.
   - Recover the original objective from the user's request and the supplied outputs.
   - Identify what the final deliverable is supposed to be.
   - Infer the expected shape from `primary` unless the user explicitly asks for a different format.
   - Detect task type: software plan, implementation design, analysis, writing, review, or another category.

2. Interrogate `alt`.
   - Extract only the non-overlapping contributions that might improve the result.
   - Look for:
     - missing risks or edge cases
     - stronger decomposition or sequencing
     - better assumptions or challenge to weak assumptions
     - omitted validation, rollout, migration, or observability work
     - sharper wording, examples, or user-facing framing
   - Classify each alt contribution as one of:
     - `adopt`: likely correct and clearly useful
     - `verify`: promising but requires checking
     - `discard`: unsupported, incorrect, or lower quality
     - `defer`: valuable but blocked on user input or missing context

3. Resolve disagreements.
   - When `primary` and `alt` conflict, do not choose based on confidence or prose quality alone.
   - Prefer ground truth in this order:
     - user-provided source material
     - local repo and codebase evidence
     - official docs, specs, or primary sources
     - informed inference, clearly labeled as inference
   - Verify high-confidence claims from both outputs, especially statements framed as "confirmed", "unchanged", "safe", or "unaffected".
   - If a high-impact disagreement remains unresolved after reasonable exploration, ask a concise blocking question.

4. Build the revised synthesis.
   - Keep the primary answer's overall shape by default.
   - Upgrade weak sections with verified improvements from `alt`.
   - Remove duplicated content, false certainty, and unsupported claims from both outputs.
   - If `primary` is structurally weak, promote the best structure from `alt` or create a new structure that still feels close to the user's expected shape.
   - Make assumptions explicit when they drive decisions.

5. Report the delta.
   - Unless the user asks for final output only, append a short section describing what changed because of `alt`.
   - Keep this section concise and evidence-based. Focus on the useful delta, not on scoring the two outputs.

## Output Defaults

Default output shape:

1. Revised synthesis
2. Short `What changed because of alt` section
3. Only the minimum open questions that remain blocking or materially decision-shaping

If the user's prompt or surrounding workflow clearly expects a different shape, honor that instead.

## Question Policy

Ask questions only when one of these is true:

- The original goal is ambiguous enough that synthesis could head in different directions.
- A conflict between `primary` and `alt` affects architecture, rollout, or scope and cannot be resolved from evidence.
- A user preference would materially change the output structure or recommendation.

When asking questions:

- Ask the minimum set.
- Make them specific.
- Explain why each answer changes the result.
- Avoid generic preference polling when a reasonable default exists.

## Planning Tasks

When the task is a software implementation plan, feature plan, migration plan, or technical design plan:

- Treat `alt` as a source of missed workstreams, hidden dependencies, rollout gaps, and faulty assumptions.
- Preserve the overall plan shape from `primary` unless it is clearly inferior.
- Validate sequencing against the actual codebase, interfaces, operational constraints, and known project conventions when available.
- Prefer a merged plan that is implementation-ready enough to guide work, not just a critique of the two plans.
- If the repo already contains partial implementation or active branch changes, distinguish clearly between:
  - already implemented or already in progress
  - remaining design decisions
  - remaining rollout, validation, and cleanup work
- Read [references/software-plan-checklist.md](./references/software-plan-checklist.md) before finalizing the output.

## Anti-Patterns

- Do not act like a judge whose only job is to pick a winner.
- Do not blindly trust `alt` because it sounds more thoughtful or more skeptical.
- Do not preserve the primary structure when that structure hides critical work or creates confusion.
- Do not import factual claims from either output without checking when verification is feasible.
- Do not ask the user broad questions you can answer by reading the repo, prompt, or supplied artifacts.
