# GPT-5.2 Prompting Guide

Reference: [OpenAI GPT-5.2 Prompting Guide](https://cookbook.openai.com/examples/gpt-5/gpt-5-2_prompting_guide)

## Core Behavioral Characteristics

GPT-5.2 exhibits **more deliberate scaffolding** and **generally lower verbosity** compared to earlier versions. It demonstrates stronger instruction adherence but maintains prompt sensitivity, requiring explicit articulation of preferences.

## Key Prompting Strategies

### 1. Verbosity Control

Provide concrete length constraints tailored to task complexity:

```xml
<verbosity>
- Simple queries: ≤2 sentences
- Complex tasks: 1 overview paragraph + ≤5 tagged bullets
- Avoid long narrative paragraphs; favor compact, structured formats
</verbosity>
```

**Example:**
```xml
<output_length>
Keep responses concise:
- Direct questions: 1-2 sentences maximum
- Analysis tasks: brief summary paragraph followed by ≤5 bullet points
- Code explanations: inline comments only, no prose preamble
</output_length>
```

### 2. Scope Discipline

GPT-5.2 can drift into over-engineering. Explicitly forbid scope creep:

```xml
<scope>
Produce EXACTLY and ONLY what the user requests. Do not:
- Add features beyond the specification
- Suggest improvements unless asked
- Expand task scope without explicit approval
When requirements are ambiguous, choose the simplest valid interpretation.
</scope>
```

### 3. Long-Context Handling

For inputs exceeding ~10k tokens, add explicit grounding instructions:

```xml
<long_context_protocol>
Before answering:
1. Produce an internal outline of relevant sections from the provided documents
2. Re-state user constraints to confirm understanding
3. Anchor all claims to specific document sections (cite page/section numbers)
4. Do not speak generically—reference source material directly
</long_context_protocol>
```

### 4. Ambiguity Management

Configure explicit behavior for uncertain or underspecified inputs:

```xml
<ambiguity_handling>
When the request is underspecified:
1. Call out the ambiguity explicitly
2. Present 2-3 plausible interpretations with labeled assumptions
3. Proceed with the most likely interpretation OR ask for clarification (specify which behavior you prefer)
Never fabricate specifics when uncertain—state uncertainty clearly.
</ambiguity_handling>
```

### 5. Structured Extraction

For document processing and data extraction, provide explicit schemas:

```xml
<extraction_schema>
Extract data into this exact JSON structure:
{
  "field_name": "string | null if not found",
  "numeric_field": "number | null if not found",
  "array_field": ["items"]
}

Rules:
- Set missing fields to null; do not guess or infer
- Re-scan source document for completeness before returning
- Flag low-confidence extractions with a confidence score
</extraction_schema>
```

### 6. Tool Integration

Optimize tool-calling with crisp descriptions and parallelism guidance:

```xml
<tool_usage>
Tool descriptions must be:
- 1-2 sentences maximum
- Action-oriented (what the tool does, not what it is)

Execution patterns:
- Execute independent tool calls in parallel
- For high-impact actions (file writes, API calls), require verification before execution
- Chain dependent operations sequentially
</tool_usage>
```

### 7. Agentic Communication

Keep agent status updates minimal and outcome-focused:

```xml
<agentic_updates>
Report status only at major phase changes:
- Task started → Task completed
- Significant blocker encountered
- User input required

Updates must include:
- Concrete outcomes (what was done, what was found)
- NOT routine narration of steps
- NOT expansion of task scope without explicit flagging
</agentic_updates>
```

## Reasoning Effort Configuration

When migrating prompts to GPT-5.2:

| Source Model | Recommended `reasoning_effort` |
|--------------|-------------------------------|
| GPT-4o / GPT-4.1 | `"none"` |
| GPT-5 | Maintain existing setting |
| GPT-5.1 | Preserve current configuration |

## High-Risk Output Safeguards

For sensitive domains (medical, legal, financial), add self-check protocols:

```xml
<high_stakes_validation>
Before returning answers in sensitive domains:
1. Scan for unstated assumptions—make them explicit
2. Verify specific claims are grounded in provided context
3. Soften absolute language: replace "always," "guaranteed," "definitely" with hedged alternatives
4. Add appropriate disclaimers for professional advice
</high_stakes_validation>
```

## Web Research Patterns

For comprehensive research workflows:

```xml
<research_protocol>
- Specify research depth upfront (surface scan vs. deep investigation)
- Cover all plausible user intents without asking clarifying questions
- Include citations for ALL web-derived information
- Define acronyms on first use
- Provide concrete examples for abstract concepts
</research_protocol>
```

## Migration Best Practices

When upgrading prompts from earlier GPT models to GPT-5.2:

1. **Switch models first, keep prompts identical** — Establish baseline behavior
2. **Run evaluations** — Compare outputs against expected results
3. **Adjust incrementally** — Modify `reasoning_effort` or constraints only after baseline testing reveals regressions
4. **Test edge cases** — GPT-5.2's stricter adherence may break prompts that relied on model "helpfulness" to fill gaps

## GPT-5.2 vs Other Models

| Aspect | GPT-5.2 | Claude 4.x | Gemini 3.x |
|--------|---------|------------|------------|
| Default verbosity | Low | Medium-High | Low |
| Instruction adherence | Very strict | High | High |
| Scope discipline | Needs explicit constraints | Naturally conservative | Needs explicit constraints |
| Parallel tool calls | Excellent | Excellent | Good |
| Long-context handling | Strong with grounding | Strong | Strong |

## Anti-Patterns to Avoid with GPT-5.2

1. **Vague length instructions** — "Be concise" is insufficient; specify exact limits
2. **Implicit scope** — Always state what is NOT in scope
3. **Assuming helpfulness fills gaps** — GPT-5.2 adheres strictly; fill all specification gaps
4. **Verbose tool descriptions** — Keep to 1-2 sentences
5. **Status update verbosity** — Model may over-report; explicitly constrain updates
