# Gemini 3.x Prompting Guide

Reference: [Gemini 3 Prompt Practices](https://www.philschmid.de/gemini-3-prompt-practices)

## Core Behavioral Characteristics

Gemini 3.x (Gemini 3.0 Flash, Gemini 3.0 Pro) produces **concise, direct responses** by default. The model excels at multimodal tasks and has strong reasoning capabilities. It requires explicit verbosity requests for detailed output and benefits from clear structural formatting.

## Key Prompting Strategies

### 1. Request Verbosity Explicitly

Gemini defaults to brief responses. When you need detail, be explicit:

```xml
<verbosity>
Default Gemini behavior: concise, minimal output

To get detailed responses:
- "Provide a comprehensive analysis with examples"
- "Explain in detail, covering all edge cases"
- "Give a thorough response with step-by-step reasoning"

To get concise responses (default):
- No special instruction needed
- Or explicitly: "Answer in 1-2 sentences"
</verbosity>
```

### 2. Direct and Concise Prompts

Gemini responds best to streamlined instructions without excessive preamble:

```xml
<directness>
Instead of:
"I was wondering if you could possibly help me understand how the authentication system works in this codebase. I'd really appreciate a detailed explanation."

Use:
"Explain how authentication works in this codebase. Include: login flow, token management, session handling."
</directness>
```

### 3. Multimodal Integration

Gemini has strong multimodal capabilities. Reference modalities explicitly:

```xml
<multimodal>
When working with images/documents:
- "Analyze this image and describe..."
- "Extract text from this screenshot..."
- "Compare the diagrams in images 1 and 2..."

Be specific about what to extract or analyze from each modality.
Cross-reference between modalities: "Does the code in the image match the description in the document?"
</multimodal>
```

### 4. Structured Output Format

For consistent output, provide explicit schemas:

```xml
<structured_output>
Return your analysis in this exact format:

## Summary
[1-2 sentence overview]

## Key Findings
- Finding 1
- Finding 2

## Recommendations
1. [Action item]
2. [Action item]

## Confidence
[High/Medium/Low with brief justification]
</structured_output>
```

Or for JSON:

```xml
<json_schema>
Return ONLY valid JSON matching this schema:
{
  "status": "success" | "error",
  "data": {
    "items": [{"name": "string", "value": "number"}],
    "total": "number"
  },
  "metadata": {
    "processed_at": "ISO timestamp",
    "source": "string"
  }
}
</json_schema>
```

### 5. Reasoning and Chain of Thought

For complex problems, request explicit reasoning:

```xml
<reasoning>
Before providing your answer:
1. State your understanding of the problem
2. Identify key constraints and requirements
3. Consider alternative approaches
4. Explain your chosen approach
5. Provide the solution

Show your reasoning at each step.
</reasoning>
```

### 6. Tool Usage in Gemini CLI

For agentic environments like Gemini CLI:

```xml
<tool_usage>
Available tools and when to use them:
- read_file: Read file contents (prefer over shell cat)
- write_file: Create new files
- replace: Modify existing files (prefer over sed/awk)
- glob: Find files by pattern (prefer over find/ls)
- search_file_content: Search within files (prefer over grep)
- run_shell_command: Only for actual commands, not file operations
- google_web_search: Current information lookup
- web_fetch: Read specific URLs
- codebase_investigator: Broad architecture questions

Prefer specialized tools over shell commands for file operations.
</tool_usage>
```

### 7. Context Grounding

For long documents or codebases, add grounding instructions:

```xml
<grounding>
When analyzing the provided context:
1. Reference specific file paths and line numbers
2. Quote relevant code snippets
3. Do not make claims without citing source
4. If information is not in context, state that explicitly
</grounding>
```

## Agentic Harness Patterns

### Task Persistence

```xml
<persistence>
Complete the task fully without asking for permission to continue.
If you encounter an error:
1. Diagnose the root cause
2. Attempt an alternative approach
3. Only stop if fundamentally blocked

Report progress at major milestones only, not every step.
</persistence>
```

### Memory and State

Gemini CLI supports memory persistence:

```xml
<memory>
Use save_memory to persist:
- Project-specific conventions discovered
- User preferences learned during session
- Key facts that should survive across conversations

Do not save ephemeral information or session-specific context.
</memory>
```

## Output Format Control

### Code Generation

```xml
<code_format>
When generating code:
- Include only the code, no explanatory prose before/after
- Use comments sparingly—only for non-obvious logic
- Follow the existing code style in the project
- Do not include usage examples unless requested
</code_format>
```

### Analysis Output

```xml
<analysis_format>
Structure analysis as:
1. **TL;DR**: 1 sentence summary
2. **Details**: Organized by category
3. **Actions**: Numbered list if applicable

Keep each section concise. Expand only if explicitly requested.
</analysis_format>
```

## Gemini 3.x vs Other Models

| Aspect | Gemini 3.x | Claude 4.x | GPT-5.2 |
|--------|------------|------------|---------|
| Default verbosity | Low | Medium-High | Low |
| Multimodal strength | Excellent | Good | Excellent |
| Prompt style preference | Direct, concise | Explicit with motivation | Explicit with constraints |
| Memory persistence | Supported (Gemini CLI) | Via files | Via files |
| Parallel tool calls | Good | Excellent | Excellent |
| Long-context handling | Strong | Strong | Strong with grounding |

## Anti-Patterns to Avoid with Gemini 3.x

1. **Assuming verbose output** — Request detail explicitly when needed
2. **Wordy prompts** — Gemini prefers direct instructions
3. **Missing modality references** — Be explicit about which image/document to analyze
4. **Vague structure requests** — Provide exact output schemas
5. **Shell commands for file ops** — Use Gemini CLI's specialized tools
6. **Overusing memory saves** — Only persist genuinely reusable information
7. **Ignoring grounding** — Always anchor claims to source material in long contexts

## Model-Specific Features

### Gemini 3.0 Flash
- Optimized for speed and cost
- Best for: quick lookups, simple transformations, high-volume tasks
- Prompt adjustment: Keep prompts shorter; model is optimized for fast inference

### Gemini 3.0 Pro
- Full reasoning capabilities
- Best for: complex analysis, multi-step reasoning, detailed code generation
- Prompt adjustment: Can handle longer, more complex prompts with multiple constraints
