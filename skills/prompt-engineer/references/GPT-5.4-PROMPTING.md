# GPT-5.4 Prompting Guide

Reference: [OpenAI GPT-5.4 Prompting Guide](https://cookbook.openai.com/examples/gpt-5/gpt-5-4_prompting_guide)

## Core Behavioral Characteristics

GPT-5.4 is an **iterative refinement of GPT-5.2**, not a radically different model. Most solid GPT-5.2 prompts will still work, but GPT-5.4 is stronger at **coding, instruction following, tool use, multimodal understanding, and long-running agent workflows**.

For prompt authors, the practical changes are:

- GPT-5.4 handles multi-file coding and repo-specific constraints more reliably
- GPT-5.4 performs better on tool-heavy and multi-step workflows, especially when prompted with clear milestones
- GPT-5.4 is stronger at document-heavy, spreadsheet-heavy, and multimodal tasks when extraction targets are explicit
- GPT-5.4 defaults to **`reasoning: none`** unless the harness raises it, so prompts should still make planning expectations explicit

The model is more capable than GPT-5.2, but it is still sensitive to **unclear scope, vague success criteria, and underspecified tool behavior**.

## Key Prompting Strategies

### 1. Match the Prompt to the Reasoning Budget

GPT-5.4 defaults to low-latency behavior. For simple tasks this is fine, but for coding, debugging, and multi-step workflows you should explicitly ask for lightweight planning or careful reasoning.

If you control model settings, use this baseline:

- Simple chat or low-latency tasks: `reasoning: none` or `low`
- General coding, debugging, and analysis: start with `medium`
- Hard multi-step planning or difficult implementation work: use `high`

```xml
<reasoning_guidance>
For straightforward tasks:
- Briefly restate the task and constraints
- Execute directly without unnecessary analysis

For complex tasks:
- First outline the plan in 3-6 concrete steps
- Call out key risks, dependencies, or assumptions
- Then execute and verify the result

Do not produce long reflective essays. Keep the visible plan brief, concrete, and task-oriented.
</reasoning_guidance>
```

**Practical rule:** if the task would previously have needed o3-style prompting, ask GPT-5.4 to plan, verify, and iterate explicitly.

### 2. Tighten Scope and Success Criteria

GPT-5.4 follows instructions well. That is helpful only if the prompt is precise. State what success looks like, what is out of scope, and how much initiative the model should take.

```xml
<scope_contract>
Deliver exactly the requested outcome.

In scope:
- Fix the reported bug
- Update only the files required for the fix
- Run relevant validation after changes

Out of scope:
- Unrelated refactors
- New features
- Dependency upgrades unless required to complete the task

If requirements are ambiguous, state the ambiguity and proceed with the simplest defensible interpretation.
</scope_contract>
```

This matters more in GPT-5.4 because stronger coding ability can otherwise turn into larger-than-needed solutions.

### 3. Specify Repo Conventions and Local Patterns

GPT-5.4 is strong at following local implementation patterns. Use that strength directly instead of asking for generic best practices.

```xml
<repo_alignment>
Before editing, inspect the relevant files and mirror existing:
- naming conventions
- error-handling style
- test structure
- dependency choices
- formatting and file organization

Prefer adapting the existing pattern over introducing a new abstraction.
</repo_alignment>
```

For coding prompts, include any non-negotiable rules about languages, frameworks, testing, migration safety, or review expectations.

### 4. Use Tool Preambles and Lightweight Execution Narration

GPT-5.4 benefits from short preambles before tool calls. This improves transparency and often improves tool-calling quality without requiring verbose narration.

```xml
<tool_preambles>
Before each tool call, briefly state:
1. Why this tool is the right next step
2. What information or result you expect
3. How it affects the plan

Keep each preamble to 1-2 sentences.
</tool_preambles>
```

Also steer tool behavior explicitly:

```xml
<tool_execution>
- Use specialized file and search tools instead of shell fallbacks when available
- Execute independent read/search operations in parallel
- Sequence dependent operations
- After writes, validate with the smallest relevant test, build, or check
- For high-impact actions, verify assumptions before proceeding
</tool_execution>
```

### 5. Prompt for Build-Run-Verify-Fix Loops

GPT-5.4 is notably better at long-running and multi-step agent workflows. Prompts should take advantage of that by defining checkpoints instead of only describing the final deliverable.

```xml
<execution_loop>
Work in this cycle:
1. Inspect the current state
2. Make the smallest justified change
3. Run validation
4. Diagnose failures if validation fails
5. Apply the next fix
6. Stop only when the task is fully resolved or a hard blocker is identified
</execution_loop>
```

This pattern is better than asking for one-shot perfection.

### 6. Strengthen Research and Multi-Source Synthesis Instructions

GPT-5.4 is stronger at web search and hard-to-locate information, but prompts still need explicit sourcing rules.

```xml
<research_protocol>
When using web or document sources:
- Use multiple relevant sources for non-trivial claims
- Prefer primary or official sources when available
- Reconcile disagreements explicitly
- Distinguish observed facts from inference
- Cite every material factual claim
- If evidence is incomplete, say so directly
</research_protocol>
```

This is especially important for prompts that combine local code, product docs, issue trackers, and web results.

### 7. Be Explicit for Document, Spreadsheet, and Multimodal Work

GPT-5.4 is better than GPT-5.2 at document understanding, spreadsheet-heavy workflows, and image perception. Do not waste that improvement with vague prompts like "analyze this spreadsheet."

```xml
<document_workflow>
When working with documents, spreadsheets, or images:
- State exactly what to extract, compare, summarize, or validate
- Name the fields, tables, tabs, columns, or visual elements that matter
- Define the expected output schema
- Flag missing, ambiguous, or low-confidence data explicitly
- Cross-check related sources before concluding
</document_workflow>
```

**Examples of better prompt framing:**

- "Compare the invoice totals in the spreadsheet against the contract values in the PDF and report mismatches by customer ID."
- "Read the screenshot and confirm whether the UI behavior matches the acceptance criteria in the ticket."

### 8. Control Verbosity Deliberately

GPT-5.4 supports explicit verbosity control and defaults to `medium`, but prompt wording still matters. Never rely on generic phrases like "be concise."

```xml
<verbosity>
- Direct answers: 1 short paragraph or 3 bullets maximum
- Code reviews: findings first, ordered by severity, with file references
- Implementation plans: 1 summary paragraph plus <=5 concrete steps
- Code generation: include only code unless explanation is requested
</verbosity>
```

For GPT-5.4, prompt-level verbosity instructions are still useful even when the harness also sets a verbosity parameter.

### 9. Make Assumption Handling Explicit

Improved instruction following does not remove the need for ambiguity handling.

```xml
<ambiguity_handling>
If information is missing or conflicting:
1. State the gap or conflict explicitly
2. List the assumptions you are making
3. Proceed only if the assumptions are low risk
4. If the risk is material, stop and ask for clarification
</ambiguity_handling>
```

This remains essential for prompt robustness in agentic environments.

## Agentic Harness Patterns

For Codex, CLI agents, and other tool-enabled environments, GPT-5.4 generally performs best when the prompt balances autonomy with verification.

### Persistence and Recovery

```xml
<persistence>
Continue until the task is complete.
If a step fails:
1. Diagnose the failure
2. Adjust the approach
3. Retry with the next best option

Do not stop after the first failed attempt unless blocked by missing permissions, missing context, or a destructive-risk decision.
</persistence>
```

### Milestone-Based Progress Updates

```xml
<progress_updates>
Report progress only at meaningful transitions:
- after initial discovery
- after implementation
- after validation
- when blocked

Each update should say what changed, what was learned, and what happens next.
</progress_updates>
```

### Source Grounding for Code and Docs

```xml
<grounding>
Ground claims in the actual materials you inspected:
- cite file paths for code
- cite document sections or page references when available
- separate direct evidence from inference
- do not claim a behavior you have not verified
</grounding>
```

## Anti-Patterns to Avoid with GPT-5.4

1. **Assuming the model will infer the right level of reasoning** — for complex tasks, ask for a short plan and verification loop
2. **Using vague scope language** — stronger instruction following means vague prompts produce vague execution
3. **Hard-coding unnecessary tool order** — constrain dependencies, not every step
4. **Asking for multimodal analysis without a schema** — specify what to extract and how to report it
5. **Using generic brevity cues** — define exact output length or structure
6. **Requesting progress narration for every action** — use milestone updates and short tool preambles instead
7. **Treating GPT-5.4 like a brand-new model** — start from GPT-5.2 prompts, then refine only where GPT-5.4 adds leverage
