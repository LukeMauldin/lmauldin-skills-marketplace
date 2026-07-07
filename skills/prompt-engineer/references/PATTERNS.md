# Prompt Patterns by Use Case

Reference patterns for common prompt types. Load this file when creating prompts for specific use cases.

## Agentic/Tool-Use Prompts

```xml
<persistence>
Continue working until the task is fully resolved. If an approach fails, analyze the failure and retry with a different strategy. Do not ask for permission to continue—persist autonomously.
</persistence>

<tool_awareness>
You have access to tools for: file reading, file editing, file search (glob), content search (grep), shell commands, web search, web fetch, codebase exploration, and task tracking. Use the most appropriate tool for each operation:
- Prefer specialized file tools over shell equivalents (use file read tool not `cat`, edit tool not `sed`)
- Use codebase exploration/investigator tools for broad architectural questions
- Use parallel tool calls when operations are independent
</tool_awareness>

<pre_tool_reflection>
Before calling any tool, state:
1. Why you're calling this tool
2. What data you expect to receive
3. How this advances the solution
</pre_tool_reflection>

<parallel_execution>
If multiple tool calls are independent (no data dependencies), execute them in parallel. Only sequence calls when one depends on another's output.
</parallel_execution>
```

## Research/Analysis Prompts

```markdown
## Approach
1. Decompose the research question into sub-questions
2. Use web search tools for current information; use web fetch tools to read specific URLs
3. Use content search (grep) and file search (glob) tools to find relevant code/documentation
4. Use codebase exploration/investigator tools for broad architectural understanding
5. Analyze sources independently before synthesizing
6. Develop competing hypotheses and track confidence levels
7. Cite sources for all claims (include file paths with line numbers for code)
8. Self-critique findings before presenting conclusions
```

## Code Generation Prompts

```xml
<code_exploration>
ALWAYS use the file read tool to inspect files before proposing edits. Never speculate about code you haven't read. Use file search (glob) to find files by pattern and content search (grep) to find specific code patterns. For broad questions about architecture or implementation patterns, use the codebase exploration/investigator tool.
</code_exploration>

<editing_workflow>
1. Use file read tool to understand the current implementation
2. Use file edit tool for modifications (prefer over full file write—preserve file history)
3. Use shell tool to run tests/builds after changes
4. Use task tracking tool to track multi-file refactors
</editing_workflow>

<avoid_overengineering>
Only make changes directly requested or clearly necessary. Keep solutions simple:
- Don't add features beyond what was asked
- Don't add error handling for impossible scenarios
- Don't create abstractions for one-time operations
- Don't design for hypothetical future requirements
</avoid_overengineering>

<no_hardcoding>
Implement general-purpose solutions that work for all valid inputs, not just test cases. Do not hard-code values or create workarounds for specific tests.
</no_hardcoding>
```

## Creative/Writing Prompts

```markdown
## Creative Guidelines
1. Identify the target audience and their expectations
2. Define the tone: formal, casual, technical, conversational
3. For casual tone: avoid corporate jargon and stiff phrasing
4. Self-evaluate: Does this sound authentic? Would a human write this?
```

## Long-Running/Multi-Session Prompts

```xml
<state_management>
- Track progress in structured files (e.g., progress.json, tests.json)
- Use git commits as checkpoints
- Before context limits: save current state to memory/files
- On resume: Review progress files, git logs, and test status before continuing
</state_management>

<incremental_progress>
Focus on steady advances—complete one component fully before starting the next. It's better to finish 3 things than to half-complete 10.
</incremental_progress>
```

## Output Format Control

### For Prose Output (Minimal Markdown)
```xml
<formatting>
Write in clear, flowing prose using complete paragraphs. Use standard paragraph breaks for organization. Reserve markdown only for:
- `inline code`
- Code blocks (```)
- Simple headings when necessary

Do NOT use:
- Bullet lists (unless truly discrete items)
- Bold or italics
- Numbered lists (unless explicitly requested)

Incorporate information naturally into sentences rather than fragmenting into bullet points.
</formatting>
```

### For Structured Output
```xml
<output_format>
Respond using this exact JSON schema:
{
  "summary": "string - one sentence overview",
  "findings": ["array of key findings"],
  "recommendation": "string - primary recommendation",
  "confidence": "number 0-1"
}
</output_format>
```
