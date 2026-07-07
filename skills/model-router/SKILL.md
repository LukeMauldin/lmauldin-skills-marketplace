---
name: model-router
description: "Recommend the right LLM/model class and thinking effort for engineering planning, implementation, review, docs, debugging, scouting, or mixed workflows. Use current context, handoff docs, plan files, or repo context; optionally produce a handoff prompt."
---

# Model Router

Use this skill to route a task to the right model and effort level.

The goal is not to pick the smartest model by default. The goal is to minimize total time-to-good-output while preserving acceptable quality for the task's actual risk and ambiguity.

This skill can also produce a concise handoff prompt for the recommended model when the user explicitly asks for one.

## Announce Skill Usage

Before starting substantive work, say: "I'm using the model-router skill to classify the task and recommend the fastest model that should still produce acceptable output."

## When To Use This Skill

Use this skill when one of these is true:

- The user asks which model should handle a task, document, plan, review, or implementation.
- The user wants to know whether a faster or cheaper model is good enough.
- The user has multiple workflow stages and wants different models for planning, implementation, and review.
- The user wants a recommendation grounded in both the task details and known model behavior.
- The user wants to route based on the current conversation without restating the task.
- The user wants a prompt they can paste into another model after choosing the route.

Do not use this skill when the user has already chosen a model and only wants execution.

## Core Routing Principles

- Prefer the fastest model that is still likely to succeed.
- Separate decision-making from execution. Many tasks only need frontier reasoning for the decision turn, not the implementation turn.
- Change effort before changing model families when that is sufficient. Same-family effort changes are usually lower-risk than a full model switch.
- Strong plans compress the need for frontier reasoning. If the design is already explicit, implementation can often move to a faster worker.
- High cost-of-failure work stays frontier longer: architecture, high-stakes code review, ambiguous debugging, security-sensitive changes, and complex multi-tool recovery.
- Fast coding workers can outperform frontier models on well-scoped implementation when the plan is already strong.

## References

- Read `references/frontier-model-analysis.md` when you need benchmark context, price/speed tradeoffs, or a broader comparison across families.
- Use the current conversation as task context if the user did not provide a separate artifact.

## Workflow

### 1. Establish the task source

Use the lightest source that is sufficient:

- If the user points at a plan, handoff doc, ticket, or code review, read that first.
- If the user does not provide an artifact, infer the task from the current conversation.
- If the task spans multiple stages, split them explicitly: scouting, planning, implementation, review, propagation, cleanup, and so on.

### 1a. Decide the output mode

Pick one mode:

- Routing only
- Routing plus handoff prompt

Default to routing only. Generate a handoff prompt only when the user explicitly asks for one.

### 2. Classify the task

Pick one primary class and note any secondary class:

- Scout / extraction
- Pre-planning / design discovery
- Plan generation from a good handoff
- Plan refinement / plan comparison
- Implementation from a settled plan
- Implementation with unresolved design
- Code review / architecture review
- Debugging / root cause analysis
- Document propagation / consistency sync
- Test writing / cleanup / linting
- Mixed workflow

### 3. Score the task on the three routing axes

Use these axes to decide model class:

- Ambiguity:
  - high: architecture still unsettled, multiple valid designs, or hidden edge cases likely
  - medium: core design is known but important local decisions remain
  - low: work is mostly execution, transformation, or propagation
- Cost of failure:
  - high: architectural breakage, security, rollout risk, public API risk, high regression risk
  - medium: recoverable implementation mistakes or moderate rework
  - low: drafts, summaries, propagation, boilerplate, cleanup
- Shape of work:
  - reasoning-heavy
  - tool-heavy
  - edit-heavy
  - extraction-heavy

### 4. Choose the model class

Use this decision tree:

- If ambiguity is high or cost of failure is high:
  - use a frontier planner or reviewer
- If ambiguity is medium and the task is implementation-heavy:
  - use a strong worker or a frontier model at reduced effort
- If ambiguity is low and the work is mostly transformation, propagation, or boilerplate:
  - use a fast worker

Prefer these classes:

- Frontier planner:
  - `gpt-5.4` `high` or `xhigh`
  - `gemini-3.1-pro` `high`
  - `claude-opus-4.6` `high` or `max`
- Strong worker:
  - `claude-sonnet-4.6` `medium`
  - `gpt-5.4` `medium`
  - `gpt-5.4` `low`
- Fast worker:
  - `composer-2`
  - `claude-sonnet-4.6` `low`
  - `claude-haiku-4.5`
  - `gpt-5.4` `none` or `low`
  - `gemini-3.1-flash-lite` `minimal` or `low`

### 5. Apply the software-engineering heuristics

These are the default recommendations unless task evidence overrides them:

- Architecture and design discovery:
  - primary: `gpt-5.4 high`
  - alternatives: `gemini-3.1-pro high`, `claude-opus-4.6 high/max`
- Plan generation from a good handoff:
  - primary: `gemini-3.1-pro high` for speed-sensitive work
  - primary: `gpt-5.4 high` for the strongest single-pass plan
  - avoid `claude-opus-4.6 high` when latency matters unless you want deeper critique
- Plan refinement or merging multiple plans:
  - primary: `claude-opus-4.6 high`
  - alternative: `gpt-5.4 high`
- Implementation from a strong merged plan:
  - primary: `composer-2` or another fast coding worker
  - alternative: `gpt-5.4 medium`
  - avoid `gpt-5.4 high` unless repo-wide cleanup and broad verification are explicitly in scope
- Implementation when the plan is incomplete:
  - primary: `gpt-5.4 medium`
  - alternative: `claude-sonnet-4.6 medium`
- High-stakes code review or architecture review:
  - primary: `claude-opus-4.6 high/max`
  - alternative: `gpt-5.4 high`
- Scout, extraction, grep-heavy discovery, and document propagation:
  - primary: `claude-haiku-4.5`
  - alternatives: `claude-sonnet-4.6 low`, `gpt-5.4 low`, `gemini-3.1-flash-lite minimal/low`
- Deterministic cleanup, test writing, formatting, and lint fixes:
  - primary: `claude-haiku-4.5`
  - alternatives: `gpt-5.4 none/low`, `gemini-3.1-flash-lite`

### 6. Account for known behavioral tendencies

Adjust the recommendation when a model's behavior matters as much as its raw intelligence:

- `gpt-5.4 high`:
  - strong autonomous planner and implementer
  - more likely to widen scope, remove adjacent dead code, and perform broad verification
  - use when that behavior is desired; constrain explicitly when it is not
- `claude-opus-4.6 high/max`:
  - strong at critique, synthesis, and edge-case reasoning
  - slower for settled implementation because it pays more validation and exploration cost
- `claude-sonnet-4.6 medium`:
  - strong general-purpose worker when you want Claude-style behavior without Opus latency
- `claude-haiku-4.5`:
  - best cheap extractor and utility worker
  - not a default choice for high-risk architectural or cross-boundary implementation
- `gemini-3.1-pro high`:
  - excellent fast planner
  - good first serious plan when speed matters
- `composer-2`:
  - treat as a Cursor-specific fast coding worker, not a universal frontier planner
  - strongest when the plan is already detailed and the task is implementation-heavy

### 7. Return a routing recommendation

Always return:

1. Task Classification
2. Why This Task Needs This Model Class
3. Primary Recommendation
4. Fastest Acceptable Alternative
5. Escalation Trigger
6. If multi-stage: per-stage routing

If the user asked for a handoff prompt, also return:

7. A paste-ready handoff prompt tailored to the chosen model

## Handoff Prompt Mode

Use this mode only when the user explicitly asks for a prompt to hand work to another model.

### Purpose

The handoff prompt should make the chosen model more likely to succeed quickly. It should not be a generic prompt. It should reflect the target model's strengths and likely failure modes.

### What the handoff prompt must include

- task summary
- source-of-truth artifacts or conversation context
- in-scope work
- explicit out-of-scope work
- key constraints and non-goals
- expected deliverable
- verification expectations
- escalation instructions if the target model encounters ambiguity

### Model-specific shaping rules

- For `gpt-5.4 high` or `medium`:
  - explicitly constrain scope
  - say what cleanup, deletion, or refactoring is out of scope unless it is truly desired
  - tell it to avoid widening into adjacent work unless blocked
- For `claude-opus-4.6`:
  - emphasize critique, synthesis, or hard-edge-case reasoning
  - do not frame it as a speed-first worker unless that is truly the ask
- For `claude-sonnet-4.6`:
  - be concrete about deliverables and verification
  - keep the prompt implementation-facing rather than exploratory
- For `claude-haiku-4.5` or `gemini-3.1-flash-lite`:
  - keep the task tightly bounded
  - avoid open-ended architecture work
- For `composer-2`:
  - emphasize the settled plan and the exact implementation slice
  - bias toward direct execution, not rediscovery

### Guardrails

- Keep the handoff prompt concise and paste-ready.
- Do not silently invent missing requirements. If the task is underspecified, say so before writing the prompt.
- Do not turn this skill into a general prompt-writing workflow.
- If the user needs a more elaborate prompt artifact, direct them to `prompt-engineer` or `plan-refinement`.

## Output Template

Use this structure:

### Task Classification

- Primary class:
- Secondary class:
- Ambiguity:
- Cost of failure:
- Work shape:

### Recommendation

- Primary model:
- Effort:
- Why:

### Fast Alternative

- Model:
- Effort:
- What quality is being traded away:

### Escalate If

- Condition 1
- Condition 2
- Condition 3

### Multi-Stage Routing

- Planning:
- Implementation:
- Review:

### Handoff Prompt

Only include this section when explicitly requested.

```text
[paste-ready prompt for the chosen target model]
```

## Quality Bar

- Do not recommend a frontier model just because it is stronger.
- Do not recommend a cheap worker when the task still contains major design uncertainty.
- When a strong plan already exists, bias toward a faster implementer.
- When a task mixes planning and implementation, separate the stages unless there is a strong reason not to.
- Name the tradeoff directly: speed, scope control, review depth, autonomy, or risk.
- If the current conversation does not contain enough context, say what is missing and make the narrowest safe assumption.
- If handoff prompt generation is requested, keep it short and operational. Escalate prompt-design-heavy cases to `prompt-engineer` or `plan-refinement`.
