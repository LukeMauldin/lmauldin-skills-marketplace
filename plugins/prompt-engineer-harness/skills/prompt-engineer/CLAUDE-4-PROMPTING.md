# Claude 4.x Prompting Guide

Reference: [Claude 4 Best Practices](https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/claude-4-best-practices)

## Core Behavioral Characteristics

Claude 4.x (Sonnet 4, Opus 4, Opus 4.5) is **highly steerable** and responds well to direct, explicit guidance. The model may be naturally conservative—explicitly request exploration or creativity when desired. Claude excels at parallel tool execution and benefits from context/motivation for instructions.

## Key Prompting Strategies

### 1. Be Explicit and Direct

Claude 4.x responds best to clear, unambiguous instructions. State exactly what you want.

```xml
<directness>
Instead of: "Make this better"
Use: "Improve this function's performance by reducing time complexity. Refactor to use a hash map instead of nested loops."

Instead of: "Help with the code"
Use: "Review this function for null pointer exceptions and add defensive checks where needed."
</directness>
```

### 2. Provide Context and Motivation

Explain WHY instructions matter. Claude generalizes better when it understands purpose.

```xml
<motivation>
Instead of: "NEVER use ellipses"
Use: "Your response will be read aloud by a text-to-speech engine, so never use ellipses since the TTS engine cannot pronounce them."

Instead of: "Keep responses short"
Use: "This output feeds into a UI component with a 280-character limit, so responses must be under 250 characters to allow for formatting."
</motivation>
```

### 3. Thinking Keyword Sensitivity

When extended thinking is **disabled**, Claude may be sensitive to certain keywords:

```xml
<thinking_keywords>
When extended thinking is disabled, avoid:
- "think step by step"
- "think carefully"
- "think through"

Instead use:
- "consider"
- "evaluate"
- "analyze"
- "assess"
</thinking_keywords>
```

When extended thinking is **enabled**, these keywords work normally.

### 4. Encourage Exploration

Claude 4.x can be conservative. Explicitly request broader thinking when needed:

```xml
<exploration>
Don't limit yourself to the obvious solution. Consider:
- Alternative approaches that might be more elegant
- Edge cases that could affect the design
- Trade-offs between different implementation strategies

Present multiple options when the best path isn't clear.
</exploration>
```

### 5. Parallel Tool Execution

Claude excels at parallel tool calls. Explicitly enable this pattern:

```xml
<parallel_tools>
When multiple tool calls are independent (no data dependencies between them):
- Execute all independent calls in a single message
- Only sequence calls when one depends on another's output

Example: Reading 5 files that don't depend on each other → 1 parallel batch
Example: Reading a config file, then reading files based on config → 2 sequential calls
</parallel_tools>
```

### 6. Constraint Placement Strategy

Position instructions strategically based on context length:

```xml
<constraint_placement>
Short context (< 4k tokens):
- Place role and constraints at the TOP
- This anchors reasoning from the start

Long context (large codebases, documents):
- Place data/context first
- Place instructions at the END, after data
- Use bridging phrases: "Based on the information above..."
</constraint_placement>
```

### 7. Positive Instructions Over Negatives

Tell Claude what TO DO rather than what NOT to do:

```xml
<positive_framing>
Instead of: "Do not use markdown in your response"
Use: "Write your response in smoothly flowing prose paragraphs without formatting."

Instead of: "Don't be verbose"
Use: "Respond in 2-3 concise sentences."

Instead of: "Never make assumptions"
Use: "State all assumptions explicitly before proceeding."
</positive_framing>
```

## Agentic Harness Patterns

For Claude Code, Cline, and similar tool-enabled environments:

### Tool Selection Guidance

```xml
<tool_selection>
Prefer specialized tools over shell commands:
- File reading: Use Read tool, not `cat` or `head`
- File editing: Use Edit tool, not `sed` or `awk`
- File search: Use Glob tool, not `find` or `ls`
- Content search: Use Grep tool, not shell `grep`
- Codebase exploration: Use Task tool with Explore agent for broad questions
</tool_selection>
```

### Persistence and Autonomy

```xml
<persistence>
Continue working until the task is fully resolved. If an approach fails:
1. Analyze the failure
2. Identify alternative strategies
3. Retry with a different approach

Do not ask for permission to continue—persist autonomously until blocked by a fundamental constraint.
</persistence>
```

### Pre-Tool Reflection

For complex tasks, add reflection before tool calls:

```xml
<pre_tool_reflection>
Before calling any tool, briefly state:
1. Why you're calling this tool
2. What data you expect to receive
3. How this advances the solution

This reflection should be 1-2 sentences, not a detailed plan.
</pre_tool_reflection>
```

## Output Format Control

### Minimal Markdown (Prose Output)

```xml
<prose_format>
Write in clear, flowing prose using complete paragraphs. Reserve markdown only for:
- `inline code`
- Code blocks (```)
- Simple headings when structurally necessary

Do NOT use:
- Bullet lists (unless truly discrete unordered items)
- Bold or italics for emphasis
- Numbered lists (unless sequence matters)

Incorporate information naturally into sentences rather than fragmenting into bullet points.
</prose_format>
```

### Structured Output (JSON)

```xml
<json_output>
Respond using this exact JSON schema:
{
  "summary": "string - one sentence overview",
  "findings": ["array of key findings"],
  "recommendation": "string - primary recommendation",
  "confidence": "number 0-1"
}

Return ONLY valid JSON with no additional text or markdown formatting.
</json_output>
```

## Claude 4.x vs Other Models

| Aspect | Claude 4.x | GPT-5.2 | Gemini 3.x |
|--------|------------|---------|------------|
| Default verbosity | Medium-High | Low | Low |
| Steerability | Very high | High | High |
| Conservative tendency | Yes—encourage exploration | Less so | Less so |
| Parallel tool calls | Excellent | Excellent | Good |
| Context/motivation benefit | High | Medium | Medium |
| Thinking keyword sensitivity | Yes (when thinking disabled) | No | No |

## Anti-Patterns to Avoid with Claude 4.x

1. **Ambiguous instructions** — Claude follows literally; be precise
2. **Missing motivation** — Adding "why" significantly improves adherence
3. **Negative-only constraints** — Frame as positive actions
4. **Assuming exploration** — Explicitly request when you want creative solutions
5. **Sequential tool calls for independent operations** — Leverage parallel execution
6. **Using "think" keywords without extended thinking** — Causes confusion
7. **Instructions buried in long context** — Place at the end with bridging phrases
