# Claude 4.5 Prompting Guide

Reference: Anthropic "Prompting best practices" for Claude Opus 4.6, Claude Sonnet 4.6, and Claude Haiku 4.5

This guide focuses on **prompt wording and harness behavior** for Claude 4.5-style agent prompts. It intentionally omits API-only features that do not materially change prompt construction.

## Core Behavioral Characteristics

Claude 4.5-era models are generally:

- more responsive to explicit system-prompt guidance
- better at tool use and parallel tool execution
- more concise and direct by default
- more agentic, which means they can also over-trigger on aggressive instructions
- stronger at long-horizon work, but more prone to over-exploration if the prompt rewards thoroughness too broadly

For a code agent generating prompts, the main implication is: **keep the proven Claude 4 structure, but tighten scope, tone down overbearing tool instructions, and be explicit about when to act, when to verify, and when to stop.**

## Key Prompting Strategies

### 1. Be Explicit, Direct, and Outcome-Oriented

Claude 4.5 follows instructions closely. That only helps if the prompt clearly defines the desired action and outcome.

```xml
<task_definition>
Implement the requested change directly.

Success criteria:
- fix the reported bug
- update only the necessary files
- run relevant validation
- report any blockers or residual risks
</task_definition>
```

Prefer action verbs such as `change`, `implement`, `update`, `review`, and `verify`. Avoid soft phrasing that invites advice instead of execution.

### 2. Add Context and Motivation, Not Just Rules

Claude generalizes better when it understands why a constraint exists.

```xml
<motivation>
Your final response will be pasted into a deployment summary visible to non-engineers, so keep it factual, concise, and free of internal jargon.
</motivation>
```

This is more effective than a bare rule like "be concise" because it explains the tradeoff the model should optimize for.

### 3. Use XML Structure for Complex Prompts

Claude continues to respond well to XML tags, especially when a prompt mixes role, constraints, context, examples, and inputs.

```xml
<role>You are a senior software engineer working in an agentic coding harness.</role>
<context>
You are modifying an existing repository. Follow local conventions before introducing new abstractions.
</context>
<workflow>
Inspect relevant files, choose the smallest sufficient change, validate it, and report the result.
</workflow>
<constraints>
- Do not change unrelated files
- Do not use destructive commands without confirmation
</constraints>
```

For long or document-heavy prompts, put the large context first and the actual request near the end.

### 4. Use Examples to Lock Format and Behavior

Few-shot examples remain one of the strongest steering tools. For Claude 4.5, examples are especially useful when you need consistent tool behavior, review style, or output structure.

```xml
<examples>
  <example>
    <input>Review this patch for regressions.</input>
    <output>
      Findings first, ordered by severity, each with a file reference and a concrete explanation of impact.
    </output>
  </example>
</examples>
```

Use examples that mirror the real task closely. Avoid toy examples that accidentally teach the wrong tone or scope.

### 5. Control Output Format with Positive Instructions

Claude 4.5 is easier to steer when you describe the target format directly instead of prohibitions.

```xml
<output_format>
Write the final answer as:
- one short summary paragraph
- a flat list of concrete findings or changes only if needed
- no preamble
- no markdown tables unless the user asked for one
</output_format>
```

If you want visibility after tool use, ask for it explicitly:

```xml
<progress_reporting>
After completing a meaningful phase of work, provide a brief factual update describing what changed, what you learned, and what comes next.
</progress_reporting>
```

Do not assume Claude will narrate every action on its own. Newer Claude models often move directly to the next step unless told otherwise.

### 6. Prompt Tool Use Explicitly, but Avoid Overtrigger Language

Claude 4.5 is responsive to tool-use instructions, and forceful wording can cause over-triggering.

```xml
<tool_guidance>
Use repository-aware search and file tools when they help you inspect or edit the codebase efficiently.
Use shell commands for execution, validation, and environment inspection.
When a direct file search or read is sufficient, do that instead of delegating to a subagent.
</tool_guidance>
```

Prefer normal instructions such as "use this tool when it improves understanding" over language like "CRITICAL: you MUST always use this tool."

### 7. Encourage Parallel Tool Calls Only When Independent

Claude 4.5 is strong at parallel reads, searches, and speculative information gathering. Prompt for parallelism when it is safe, but define the dependency boundary clearly.

```xml
<parallel_execution>
If multiple tool calls are independent, make them in parallel.
If one call depends on the output of another, execute them sequentially.
Never guess missing parameters just to parallelize more aggressively.
</parallel_execution>
```

This pattern is particularly effective for reading multiple files, running several searches, or collecting independent evidence before synthesis.

### 8. Calibrate Thoroughness to Avoid Over-Exploration

Claude 4.5 can do more up-front exploration than you may want, especially in large prompts or agentic harnesses. Replace blanket "be extremely thorough" guidance with narrower instructions.

```xml
<decision_making>
Choose an approach once you have enough evidence.
Do not keep reopening settled decisions unless new evidence directly contradicts them.
Prefer the smallest sufficient investigation that can support a correct answer.
</decision_making>
```

This reduces wasted tool calls and helps the model commit to execution.

### 9. Be Careful with "Think" Language

When explicit thinking is not enabled, Claude Opus 4.5 is notably sensitive to the word `think` and close variants. If the harness is not exposing a thinking mode, prefer alternatives such as `reason through`, `evaluate`, `consider`, or `analyze`.

```xml
<reasoning_guidance>
Reason through the tradeoffs before editing.
After reviewing tool results, evaluate whether the current approach still holds.
</reasoning_guidance>
```

If a thinking mode is available, broad instructions like "think thoroughly" often work better than brittle, over-prescriptive chains of thought.

### 10. Ground Long-Context Work in Evidence

For large prompts, logs, or multi-document inputs:

- put the source material before the request
- separate documents with XML tags
- ask Claude to extract relevant quotes or evidence before synthesizing conclusions

```xml
<grounding>
Before concluding, pull the specific file excerpts or document quotes that support your answer.
Base your final answer on those excerpts rather than on vague recall from the full context.
</grounding>
```

This is one of the highest-leverage upgrades for repo analysis, incident review, and research prompts.

## Agentic Harness Patterns

For Codex, Claude Code, and similar tool-enabled environments, Claude 4.5 generally performs best when the prompt balances autonomy with boundaries.

### Default to Action Only When That Is Actually Desired

Claude may otherwise answer with suggestions instead of acting, or it may act too aggressively if your system prompt is too forceful. Be explicit either way.

```xml
<default_to_action>
By default, implement the requested change instead of only suggesting it.
If the user's intent is ambiguous, infer the most useful low-risk action and proceed.
</default_to_action>
```

Or, if you want a conservative assistant:

```xml
<conservative_mode>
Do not edit files or implement changes unless the user clearly requested action.
If intent is ambiguous, investigate and explain options before acting.
</conservative_mode>
```

### Balance Autonomy with Reversibility

Claude 4.5 is capable enough to take impactful actions. Good prompts should define which actions are safe to take autonomously and which require confirmation.

```xml
<safety_boundary>
You may take local, reversible actions autonomously, such as reading files, editing code, and running focused tests.
Ask before destructive, shared, or hard-to-reverse actions such as deleting files, force pushing, amending published commits, or modifying shared infrastructure.
</safety_boundary>
```

### Constrain Overengineering

Claude 4.5 can overengineer by adding extra abstractions, files, or speculative improvements. If you want focused execution, say so directly.

```xml
<scope_control>
Avoid over-engineering.
Do only what is directly requested or clearly necessary to complete the task correctly.
Do not add abstractions, helper files, or unrelated cleanup unless the task requires them.
</scope_control>
```

### Use Subagents Selectively

Claude 4.5-era models can delegate well, but they may overuse subagents if the prompt treats delegation as universally desirable.

```xml
<subagent_policy>
Use subagents only for parallelizable or isolated workstreams.
For simple lookups, single-file edits, or tightly coupled sequential work, operate directly in the main context.
</subagent_policy>
```

### Ask for Grounded, Non-Hallucinatory Code Answers

```xml
<grounded_analysis>
Never speculate about code you have not read.
Inspect relevant files before making claims about the implementation.
Separate verified facts from inference.
</grounded_analysis>
```

This is especially important when the prompt asks Claude to review, explain, or compare existing code.

## Practical Guidance for Prompt Authors

When a code agent is generating a prompt for Claude 4.5, the prompt should usually answer these questions clearly:

1. What concrete outcome should Claude produce?
2. Should Claude act or advise?
3. What context or files matter most?
4. Which tools should be preferred, and when?
5. What is in scope versus out of scope?
6. How much progress reporting is desired?
7. What actions require confirmation?
8. How should Claude validate or self-check the result?

If any of those are unclear, the resulting prompt is likely underspecified.

## Anti-Patterns to Avoid with Claude 4.5

1. **Overstating how much prompting force is needed**: aggressive anti-laziness or tool-triggering language can cause over-triggering and unnecessary exploration
2. **Asking for maximal thoroughness without a stopping rule**: this often produces extra searching instead of timely execution
3. **Asking for vague quality improvements**: define the outcome, scope, and validation target explicitly
4. **Using negative-only constraints**: describe the desired format and behavior directly
5. **Requesting subagents or heavy delegation by default**: direct reads and searches are often faster
6. **Forgetting to specify whether action is desired**: Claude may suggest when you wanted implementation, or implement when you wanted analysis
7. **Burying the actual request inside large context**: for long prompts, put the query and success criteria near the end
8. **Assuming progress narration will happen automatically**: ask for brief updates if they matter
9. **Prompting for ungrounded analysis of code or documents**: require file reads, quotes, or concrete evidence first
