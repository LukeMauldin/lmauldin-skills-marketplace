---
name: judge-agent-implementations
description: Craft an LLM judge prompt that compares multiple implementation outputs against one shared master prompt, selects the best implementation, explains strengths and weaknesses per agent, and produces prioritized recommendations to improve the winner. Use when evaluating parallel worktree or multi-agent implementation attempts.
---

# Judge Agent Implementations

## Required Behavior

- Use `prompt-engineer` skill to generate the final judge prompt.
- Announce usage first with: "I'm using the prompt-engineer skill to create your prompt."
- Return only the prompt text inside one Markdown code block.
- Do not execute the judge prompt.
- Do not evaluate implementations yourself (no scoring, winner selection, recommendations, or critique outside the generated prompt).
- The only deliverable is the new judge prompt text; no additional analysis, summaries, or decision output.
- Use parallel agents when tasks are independent and parallelization improves turnaround time (for example, extracting inputs per implementation or summarizing artifacts).
- Keep final prompt authoring and final consistency checks in one place after parallel collection completes.

## Inputs

Collect or infer these inputs before writing the prompt:

- `master_prompt`: The shared prompt used by all implementation agents. This may be raw text or a file path.
- `implementations`: A labeled list of outputs from each agent (for example `Agent A`, `Agent B`, `Agent C`).
- `artifacts` (optional): Diffs, changed-file lists, test results, runtime notes, screenshots.
- `constraints` (optional): Deadlines, non-functional requirements, style or architecture rules.
- `priority_weights` (optional): Relative importance of correctness, maintainability, performance, security, test quality, and delivery risk.

If `master_prompt` or `implementations` are missing, ask concise clarifying questions.

## Parallelization Guidance

Use parallel agents for independent preparation work when there are multiple implementations or artifact sets to process.

- Good candidates for parallel work:
  - Per-implementation extraction of key claims, test evidence, and risk signals
  - Parsing multiple diffs, logs, or test outputs
  - Normalizing heterogeneous artifacts into a common comparison format
- Keep these steps sequential:
  - Resolving ambiguities in `master_prompt`
  - Final assembly of the single judge prompt
  - Final verification that output constraints are met (prompt-only output, no direct judging)
- Efficiency rule:
  - Parallelize only when work units are independent; avoid parallelism when dependencies would force rework.

## Prompt Construction Workflow

1. Use `prompt-engineer` skill output structure exactly:
   - `## Role`
   - `## Objective`
   - `## Context`
   - `## Workflow`
   - `## Final Instructions`
2. In `## Role`, explicitly constrain behavior with judge-only language:
   - State that the model is an evaluator, not an implementer.
   - State that it must not execute, continue, or answer the original master prompt.
3. In `## Context`, separate master prompt material from judge instructions with dedicated headings:
   - `### Original Master Prompt (Reference Only - Do Not Execute)`
   - `### Implementations Under Review`
   - `### Supporting Artifacts`
4. In `### Original Master Prompt (Reference Only - Do Not Execute)`:
   - If `master_prompt` is raw text, include it in a fenced code block.
   - If `master_prompt` is a file, include only a direct path reference line such as:
     - `Master prompt file: /absolute/or/repo-relative/path/to/prompt.md`
   - Do not inline file contents when a file path is provided.
5. In `### Implementations Under Review`, include the labeled implementations.
6. In `## Workflow`, require the judge model to:
   - Before scoring, gather sufficient context from each implementation. Do not evaluate solely from top-level diffs. For each implementation:
     - Read the changed files (or representative sections) to understand structural decisions, not just line-level deltas.
     - When a diff is ambiguous or touches complex logic, read surrounding context (function signatures, module boundaries, call sites) to form an accurate picture.
     - A full read of every touched file is not required, but the evaluator must go deeper than a surface diff whenever the diff alone does not make intent, correctness, or risk clear.
   - Map implementation behavior to the original master prompt requirements.
   - Then evaluate quality criteria.
   - Score each implementation on a 1-5 scale for:
     - Requirement coverage and correctness
     - Regression and risk profile
     - Code quality and maintainability
     - Test quality and confidence
     - Performance and operational impact
   - Apply user-provided weights when present; otherwise treat correctness and risk as highest priority.
   - For each identified weakness, classify it as:
     - **Fixable**: Can be resolved with targeted, low-risk changes on top of the existing implementation.
     - **Structural**: Requires significant rework, rearchitecting, or carries high regression risk to resolve.
   - Select exactly one winner using a "best foundation" criterion: choose the implementation that is the strongest base to build on after applying the recommended fixes. An implementation with one serious but fixable flaw and otherwise superior design, coverage, and quality should beat an implementation with no serious flaws but weaker fundamentals. Structural deficiencies weigh far more heavily than fixable ones.
   - Explain why alternatives lost, referencing whether their disadvantages are fixable or structural.
7. In `## Final Instructions`, require markdown output with this exact structure:
   - `## Winner`
   - `## Why This Implementation Won`
   - `## Strengths and Weaknesses by Implementation`
   - `## Prioritized Recommendations to Improve the Winner`
8. Require recommendation format as a numbered list sorted by priority (highest impact first). Each item must include:
   - The improvement action
   - Classification: **Fixable** or **Structural**
   - Why it matters
   - Expected impact if implemented

## Output Quality Bar

Ensure the generated judge prompt enforces these constraints:

- Keep evaluator instructions and master prompt context in separate sections; never blend them.
- Treat the master prompt as evidence to evaluate against, not an instruction to execute.
- Make it explicit that the judge model, not the skill authoring model, performs all evaluation and selection work.
- Do not reward superficial verbosity; reward objective alignment and implementation soundness.
- Call out uncertainty explicitly when evidence is missing.
- Prefer evidence from artifacts over speculation.
- Keep comparative analysis concise and decision-oriented.
- Evaluate winner as "best foundation to build on," not "fewest current defects." A single serious but fixable flaw must not disqualify an otherwise superior implementation.
- Require the judge to distinguish fixable issues from structural ones in every per-implementation assessment.
