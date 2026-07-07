# Frontier Model Routing Analysis for Software Engineering Agent Harnesses

> **Purpose:** This document is a comprehensive reference for an LLM that inspects agent-harness session logs (Claude Code, Cursor, Codex, custom harnesses) and decides which conversation segments can be moved off expensive frontier models onto faster, cheaper models without materially hurting outcomes.
>
> **Scope:** Software engineering work broadly — not just writing code, but also document analysis, tool calling, project management tasks, general analysis, test strategy, code review, and all the surrounding work that happens in real SE sessions.
>
> **Date compiled:** April 1, 2026. All numbers are point-in-time snapshots.

---

## How To Read This Document

Two details matter enormously for harness-log routing:

1. **Output speed is not the same as time-to-first-answer.** Reasoning models can stream quickly once they start answering but still spend a long time "thinking" before the first visible answer token. That hidden thinking time matters a lot for agent loops where the harness is waiting for the model to begin responding before it can take the next action.

2. **Thinking settings can change a model's effective class more than the model name does.** For example, `GPT-5.4` with `reasoning.effort: none` behaves like a strong non-reasoning model, while `GPT-5.4` with `xhigh` behaves like a slow frontier planner. Claude Sonnet 4.6 at `low` effort is much closer to a fast worker than to Opus-style deep reasoning. Always consider adjusting effort level before switching model families — effort changes are lower-risk than model switches because they preserve instruction-following quirks and tool-calling patterns.

---

## Executive Summary

### Best frontier planners (Tier A)

1. **Gemini 3.1 Pro Preview** and **GPT-5.4** — effectively tied at the top on broad reasoning (both AA Intelligence Index 57). Gemini 3.1 Pro excels at multimodal and science reasoning. GPT-5.4 is the strongest unified model for coding + computer use + tool orchestration.
2. **GPT-5.3-Codex** — just behind at AA 54, still one of the strongest pure agentic coding models.
3. **Claude Opus 4.6** — AA 53 at adaptive max. Elite for coding, nuanced professional work, and multi-agent orchestration. #1 on Arena.ai Elo leaderboard (1504).
4. **Claude Sonnet 4.6** — AA 52 in strongest evaluated adaptive profile. Very close to Opus; often the better price-performance default for frontier work.

### Best downgrade targets

- **Claude Sonnet 4.6 at `low` or `medium` effort** — for implementation turns that don't need Opus-class depth but still need reliable tool calling and code quality
- **Claude Haiku 4.5** — for cheap subagents, extraction, synthesis, classification, straightforward code edits, document summarization
- **Gemini 3.1 Flash Lite** — for very high-throughput reasoning-lite or medium-difficulty work where speed and cost dominate
- **GPT-5.4 with `none` or `low` effort** — when you want to stay on the same family but stop paying for frontier reasoning on routine turns
- **GPT-5.3-Codex-Spark** — for ultra-fast interactive coding turns where latency matters more than deep planning (currently limited availability)

### Main routing conclusion

A large fraction of agent-harness traffic does not need a top-tier frontier planner. In most SE sessions, the following segments are good downgrade candidates: status updates, repo summarization after local exploration, log triage with obvious errors, deterministic code transforms, formatting and cleanup passes, shallow grep and file discovery, extracting next steps from already-known context, simple tests of one hypothesis, first-pass doc drafting, commit message generation, subagent tasks with narrow ownership and clear acceptance criteria, boilerplate test writing, and routine project management updates.

The parts that still justify frontier models are: novel architecture decisions, ambiguous root-cause analysis, long-horizon planning over many files or tools, tough agent recovery after several failed attempts, high-stakes code review and final validation, difficult multimodal or computer-use tasks, hard reasoning over large context, security-sensitive code changes, and complex document analysis requiring cross-reference reasoning.

---

## Important Caveats For The Downstream Router

- **Cursor Composer 2** is not a general-purpose public API model. It is a product-specific coding model and IDE experience. Treat it as a specialized coding worker in Cursor-specific traces, not a generic routing target. Despite strong benchmark numbers, real-world users consistently report it is less intelligent than GPT-5.4-class models for non-trivial reasoning. Place it in Tier B (strong worker), not Tier A.
- **GPT-5.3-Codex-Spark** is a research-preview, latency-first coding model. It is not broadly available via public API — currently limited to ChatGPT Pro and design-partner access. Public pricing and reasoning-control documentation are limited. It has known issues with tool-call formatting reliability (missing JSON fields, phantom parameters).
- **GPT-5.4 Pro** ($30/$180 per 1M tokens) is excluded from this analysis — too expensive for routine agent harness use.
- Anthropic, OpenAI, and Google all expose reasoning/thinking controls differently. Do not assume effort names are interchangeable across providers.
- For reasoning models, very large TTFT numbers usually reflect deliberate hidden reasoning before the answer, not poor token streaming throughput.

---

## Normalized Comparison Table

| Model | Provider | Release | Thinking Controls | Context | Price ($/1M in/out) | AA Intelligence | Speed (t/s) | TTFT | Routing Role |
|-------|----------|---------|-------------------|---------|--------------------|-----------------|-----------|----|--------------|
| GPT-5.4 | OpenAI | Mar 5, 2026 | `none`, `low`, `medium`, `high`, `xhigh` | 1.05M in, 128K out | $2.50 / $15 | 57 (`xhigh`); 35 (non-reasoning) | 74.4 (`xhigh`); 68.3 (non-reasoning) | ~185–204s (`xhigh`); 0.90s (non-reasoning) | Best general orchestrator; hardest-task solver |
| Gemini 3.1 Pro | Google | Feb 19, 2026 | `low`, `high` (cannot fully disable thinking) | 1M in, 64K out | $2 / $12 (2x above 200K) | 57 | 111.6 | 27.35s | Top-tier planner; multimodal & long-context |
| GPT-5.3-Codex | OpenAI | Feb 24, 2026 | Similar to GPT-5.4 effort levels | 400K in, 128K out | $1.75 / $14 | 54 | 72 | — | Elite pure coding & agentic code |
| Claude Opus 4.6 | Anthropic | Feb 5, 2026 | `low`, `medium`, `high`, `max` | 200K (1M beta) | $5 / $25 | 53 (`max`); 46 (non-reasoning) | 45.7 (`max`); 42.0 (non-reasoning) | 21.56s (`max`); 1.76s (non-reasoning) | High-end planner & reviewer; expensive |
| Claude Sonnet 4.6 | Anthropic | Feb 17, 2026 | `low`, `medium`, `high` (no `max`) | 200K (1M beta) | $3 / $15 | 52 (adaptive); 44 (non-reasoning high); 43 (non-reasoning low) | 52.1 (adaptive); ~43–58 (non-reasoning) | 114.92s (adaptive); faster non-reasoning | Strong default worker; most frontier turns can shift here |
| Claude Haiku 4.5 | Anthropic | Oct 15, 2025 | Extended thinking via manual `budget_tokens` (no named effort levels) | 200K | $1 / $5 | 37 (reasoning); 31 (non-reasoning) | 100.1 (reasoning); 88.4 (non-reasoning) | 12.62s (reasoning) | Cheap subagent, extractor, classifier, light coder |
| Gemini 3.1 Flash Lite | Google | Mar 3, 2026 | `minimal`, `low`, `medium`, `high` (`minimal` ≈ near-no-thinking) | 1M | $0.25 / $1.50 | 34 | 289.8–388.8 | 5.18–6.46s | High-volume downgrade target |
| GPT-5.3-Codex-Spark | OpenAI/Cerebras | Feb 12, 2026 | Not publicly configurable; fixed latency-first behavior | 128K (text-only) | No public API pricing (research preview) | Below GPT-5.3-Codex by design | 1,000+ | Near-instant | Ultra-fast interactive coding loop |
| Composer 2 | Cursor | Mar 19, 2026 | Not exposed via standard API controls | Cursor-managed | $0.50 / $2.50 (fast: $1.50 / $7.50) | TB2: 61.7; SWE-ML: 73.7 (Cursor-reported) | MoE-optimized | — | Cursor-specific coding worker; not a general routing target |

---

## Relative Intelligence Ordering

This section is the most important for a routing LLM.

### Frontier reasoning order (using Artificial Analysis Intelligence Index and positioning)

1. **Gemini 3.1 Pro Preview (`high`)** and **GPT-5.4 (`xhigh`)** — effectively tied at top (both AA 57)
2. **GPT-5.3-Codex (`xhigh`)** — half-step down overall (AA 54) but especially strong for coding and agentic code work
3. **Claude Opus 4.6 (`max`)** — just behind at AA 53; elite for coding, enterprise agents, nuanced professional work; #1 Arena.ai Elo
4. **Claude Sonnet 4.6 (adaptive)** — very close to Opus in strongest evaluated profile (AA 52); often the better price-performance default
5. **Claude Haiku 4.5 (reasoning)** — meaningfully weaker than frontier leaders (AA 37) but much cheaper and faster
6. **Gemini 3.1 Flash Lite** — weaker than frontier (AA 34) but unusually strong for its speed and price
7. **Composer 2** — strong coding benchmarks (SWE-bench Multilingual 73.7) but real-world users consistently find it less capable than frontier models on non-trivial reasoning, debugging recovery, and architectural decisions; treat as Tier B worker, not Tier A planner
8. **GPT-5.3-Codex-Spark** — below GPT-5.3-Codex in raw intelligence by design; its value is latency, not top-end reasoning; known tool-call reliability issues

### Software engineering task-specific interpretation

| SE Task Category | Best Models | Acceptable Downgrade | Notes |
|-----------------|------------|---------------------|-------|
| Architecture & system design | GPT-5.4 (xhigh), Gemini 3.1 Pro, Opus 4.6 (max) | Sonnet 4.6 (high) | High cost-of-failure; don't downgrade further |
| Complex debugging / root cause | Opus 4.6, GPT-5.4, Sonnet 4.6 (high) | — | Keep frontier; especially after failed attempts |
| Multi-file refactoring | Sonnet 4.6, GPT-5.3-Codex, Opus 4.6 | Haiku 4.5 for individual file changes | Split: plan with frontier, execute with worker |
| Code review (high-stakes) | Opus 4.6, GPT-5.4 | Sonnet 4.6 (medium) | Security-sensitive → stay frontier |
| Feature implementation | Sonnet 4.6 (medium), GPT-5.3-Codex | Haiku 4.5, Flash Lite | Most implementation is plan-execution |
| Test writing | Sonnet 4.6 (low), Haiku 4.5 | Flash Lite | Tests for known behavior → cheap model |
| Document analysis & comprehension | Sonnet 4.6, Opus 4.6, Gemini 3.1 Pro | Haiku 4.5 for simple extraction | Sonnet matches Opus on OfficeQA benchmark |
| Tool calling & function orchestration | GPT-5.4 (54.6% Toolathlon), Sonnet 4.6 | Haiku 4.5 for simple tool chains | Spark has known tool-call formatting issues |
| Computer use / browser automation | GPT-5.4 (75% OSWorld) | GPT-5.4 Mini (72.1% OSWorld) | Large gap to other models; GPT-5.4 family dominates |
| Project management tasks | Sonnet 4.6 (medium), Haiku 4.5 | Flash Lite | Status updates, task breakdowns, summaries |
| Commit messages & changelogs | Haiku 4.5, Flash Lite | GPT-5.4 Nano if available | Trivial task; use cheapest available |
| Log triage & error classification | Haiku 4.5, Flash Lite | — | Clear stack traces don't need frontier reasoning |
| API/SDK documentation reading | Sonnet 4.6 (low), Haiku 4.5 | Flash Lite | Extraction from known sources |
| Sprint planning & estimation | Sonnet 4.6 (medium) | Haiku 4.5 for formatting | Planning quality matters; execution doesn't |
| Code formatting & linting fixes | Haiku 4.5, Flash Lite, Spark | — | Deterministic; cheapest model wins |
| Repo exploration & search | Haiku 4.5, Flash Lite | — | Grep/find/list operations; no reasoning needed |

---

## Per-Model Detailed Notes

---

### GPT-5.4

**Provider:** OpenAI | **Model ID:** `gpt-5.4` | **Release:** March 5, 2026

#### What it is
OpenAI's frontier flagship. First general-purpose model with native state-of-the-art computer-use capabilities, agentic coding, and professional workflows in a unified architecture. Supports up to 1.05M context (922K input + 128K output).

#### Intelligence & benchmarks
- **AA Intelligence Index:** 57 (`xhigh`); 35 (non-reasoning)
- **SWE-bench Pro:** 57.7%
- **OSWorld (computer use):** 75% — exceeds human expert testers (72.4%)
- **GDPval:** 83%
- **BrowseComp:** 82.7%
- **ARC-AGI-2:** 73.3%
- **Toolathlon (tool orchestration):** 54.6% — strongest for multi-tool chaining

#### Pricing
| Condition | Input ($/1M) | Output ($/1M) |
|-----------|-------------|--------------|
| Standard | $2.50 | $15.00 |
| >272K context | $5.00 | $15.00 |

#### Speed & latency
- **`xhigh` effort:** 74.4 t/s output, but **~185–204s TTFT** (long hidden thinking)
- **Non-reasoning:** 68.3 t/s, **0.90s TTFT** (fast, suitable for interactive use)
- Tool-search configuration reduced total token usage by 47% while maintaining accuracy

#### Thinking controls
Six levels: `none`, `low`, `medium`, `high`, `xhigh`. This is the most granular effort control of any provider. Critical for routing because:
- `none` / `low` → strong non-reasoning worker (fast, cheap per-turn)
- `medium` / `high` → balanced reasoning
- `xhigh` → full frontier planner (slow, expensive per-turn)

#### SE-relevant strengths
- Best tool orchestration reliability (Toolathlon 54.6%)
- Best computer use / browser automation (OSWorld 75%)
- Strong at mixed workflows: coding + tool use + document analysis in one turn
- 1M+ context allows entire codebases in a single prompt

#### Routing interpretation
**Use for:** ambiguous architecture, high-stakes review, difficult bug hunts after cheaper attempts failed, complicated browser or tool workflows, large-context repo reasoning, mixed coding+analysis tasks.

**Downgrade away for:** routine execution after plan is known, straightforward code edits, summary generation, deterministic transforms, tool-call glue code, subagent work with narrow scope, PM status updates.

**Key insight:** If a harness can switch effort dynamically, that may matter more than switching model families. GPT-5.4 at `none` is a strong, fast worker; at `xhigh` it's a deep planner. Same API endpoint, radically different behavior.

---

### GPT-5.3-Codex

**Provider:** OpenAI | **Model ID:** `gpt-5.3-codex` | **Release:** February 24, 2026

#### What it is
OpenAI's most advanced agentic coding model. Combines frontier SE performance of GPT-5.2-Codex with broader reasoning capabilities. Purpose-built for coding workflows.

#### Intelligence & benchmarks
- **AA Intelligence Index:** 54
- **SWE-bench Pro:** ~72% (state-of-the-art at release)
- **Terminal-Bench 2.0:** 77.3%
- **OSWorld-Verified:** 64.7%
- **SWE-Lancer IC Diamond:** 81.4%

#### Pricing & speed
- $1.75 / $14.00 per 1M tokens
- 72 t/s (above average for reasoning models in its price tier)
- 400K context, 128K max output

#### Thinking controls
Supports reasoning effort configuration similar to GPT-5.4.

#### Routing interpretation
**Use for:** dedicated coding agent workflows, complex multi-file refactoring, terminal/CLI tasks, pure SE work where coding quality matters more than general knowledge.

**Note:** GPT-5.4 has largely superseded this model for new deployments, but it remains a strong choice if your harness is already using it and switching would be disruptive. Slightly cheaper input pricing ($1.75 vs $2.50) but more expensive output ($14 vs $15 is negligible).

---

### GPT-5.3-Codex-Spark

**Provider:** OpenAI (Cerebras hardware) | **Model ID:** `gpt-5.3-codex-spark` | **Release:** February 12, 2026

#### What it is
OpenAI's first model designed for real-time coding. A smaller distillation of GPT-5.3-Codex optimized for ultra-low latency on Cerebras hardware. 15x faster than standard GPT-5.3-Codex.

#### Intelligence & benchmarks
- **SWE-bench Pro:** ~56.8% (vs. Codex's ~72%)
- **Terminal-Bench 2.0:** ~58.4% (estimated; vs. Codex's 77.3%)
- Intentionally trades ~15 points of SWE-bench for massive speed gains

#### Pricing & availability
- **Research preview only** — ChatGPT Pro users and design partners
- No broadly published public API pricing
- Not available on OpenRouter as of April 2026
- Separate usage limits due to specialized Cerebras hardware

#### Speed
- **1,000+ tokens/second** — fastest model in this analysis by a wide margin
- Near-instant feel for coding tasks
- 128K context window (text-only, no images)

#### Thinking controls
Not publicly documented as configurable. Treat as fixed latency-first behavior — not a configurable deep-reasoning model.

#### Known limitations
- **Tool-call reliability issues:** Multiple reports of unreliable tool-call formatting — JSON schemas with missing fields, function signatures with phantom parameters. This is a significant concern for structured agent harnesses that depend on reliable tool calling.
- **Small context:** 128K is the most limited in this set — only suitable for focused, single-file or small multi-file tasks
- **No images:** Text-only
- Falls apart on multi-step architecture and stateful debugging

#### SE-relevant best use cases
- Rapid prototyping and iterative frontend development
- Targeted single-file edits where the fix is already understood
- Real-time code completion loops
- Quick patch generation
- Code cleanup and formatting
- Short feedback loops with a human actively steering

#### SE tasks to avoid
- Novel architecture decisions
- Deep debugging with multiple interacting hypotheses
- Tasks requiring large context (>128K)
- Anything requiring reliable structured tool calling
- Multi-file reasoning with complex interdependencies

#### Routing interpretation
Spark is the clearest candidate for replacing frontier models in tight edit loops. Think of it as the "typing speed" layer — when the problem is already understood and the model just needs to produce code fast. Do not use it as the "thinking" layer.

**Critical availability note:** Because Spark is not broadly available via public API, a routing system should only target it if the harness has confirmed access. Otherwise, use Claude Haiku 4.5 or Gemini 3.1 Flash Lite as the fast-and-cheap alternative.

---

### Claude Opus 4.6

**Provider:** Anthropic | **Model ID:** `claude-opus-4-6` | **Release:** February 5, 2026

#### What it is
Anthropic's most capable model. Plans more carefully, sustains agentic tasks for longer, and operates reliably within large codebases. #1 on Arena.ai text leaderboard (Elo 1504, March 2026).

#### Intelligence & benchmarks
- **AA Intelligence Index:** 53 (adaptive `max`); 46 (non-reasoning)
- **Humanity's Last Exam:** Highest score among all frontier models
- **Terminal-Bench 2.0:** Highest score for agentic coding
- **GDPval-AA:** Outperforms GPT-5.2 by ~144 Elo points
- **BrowseComp:** Highest score for hard-to-find information retrieval
- **MRCR v2 (8-needle, 1M):** 76% — exceptional long-context retrieval
- **SWE-bench Verified:** 80.8%
- Strong at root cause analysis, multilingual coding, cybersecurity, life sciences

#### Pricing
| Condition | Input ($/1M) | Output ($/1M) |
|-----------|-------------|--------------|
| Standard | $5.00 | $25.00 |
| >200K context (1M beta) | $10.00 | $37.50 |
| Fast Mode | $30.00 | $150.00 |

#### Speed & latency
- **Adaptive `max`:** 45.7 t/s, 21.56s TTFT
- **Non-reasoning:** 42.0 t/s, 1.76s TTFT
- Fast Mode: up to 2.5x faster at 6x standard pricing

#### Thinking controls
Adaptive thinking with `effort` parameter: `low`, `medium`, `high` (default), `max` (Opus-only). Older manual thinking-budget mode still works but is deprecated. At `medium` effort, matches Sonnet 4.5's SWE-bench score while using 76% fewer output tokens — a key cost optimization lever.

#### SE-relevant strengths
- Best sustained agentic coherence over long sessions (Vending-Bench 2)
- Exceptional long-context retrieval (76% MRCR at 1M)
- Agent Teams (Claude Code): multiple agents coordinate autonomously in parallel
- Context compaction: automatically summarizes older context during long conversations
- Lowest over-refusal rate among recent Claude models
- Strong document comprehension (OfficeQA)

#### Routing interpretation
Opus 4.6 is **rarely the right default for all turns** in an agent session. It is usually the right **escalation target**.

**Good use:** rescue turns after failures, final review before merge/deploy, hardest planning, tasks where a wrong answer is very expensive, multi-agent orchestration, complex document analysis requiring cross-reference reasoning.

**Bad use:** progress updates, search and browse triage, rote refactors, repetitive agent execution, simple file operations, boilerplate generation.

---

### Claude Sonnet 4.6

**Provider:** Anthropic | **Model ID:** `claude-sonnet-4-6` | **Release:** February 17, 2026

#### What it is
Frontier intelligence at scale. The closest thing in this set to a practical default frontier worker. Developers with early access preferred Sonnet 4.6 over Opus 4.5 59% of the time. Default model on Claude Free and Pro plans.

#### Intelligence & benchmarks
- **AA Intelligence Index:** 52 (adaptive); 44 (non-reasoning high); 43 (non-reasoning low)
- **Claude Code preference:** Preferred over Sonnet 4.5 ~70% of the time
- **OfficeQA:** Matches Opus 4.6 on enterprise document comprehension
- **Insurance benchmarks:** 94% accuracy on specialized workflows
- **Computer Use (OSWorld):** Human-level on spreadsheet navigation and multi-step web forms
- **SWE-bench Verified:** 79.6%
- Close to Opus on bug detection; excels at searching across large codebases

#### Pricing
$3.00 / $15.00 per 1M tokens (same price regardless of context length within 200K; 1M beta available)

#### Speed & latency
- **Adaptive (strongest):** 52.1 t/s, 114.92s TTFT
- **Non-reasoning high:** 43.4 t/s (much faster TTFT)
- **Non-reasoning low:** ~43–58 t/s (fastest practical mode)

#### Thinking controls
Effort levels: `low`, `medium`, `high`. No `max` (Opus-only). Anthropic recommends `medium` as default for most applications and `low` for high-volume or latency-sensitive workloads. Performs strongly even with extended thinking disabled.

#### SE-relevant strengths
- Excellent tool calling with fine-grained tool streaming (GA on all platforms)
- Matches Opus on document comprehension (OfficeQA)
- Strong computer use with resistance to prompt injection
- Web search and fetch with automatic code execution for filtering
- Context compaction (beta)
- "Perfect design taste" per early users — strong for frontend/design tasks

#### Routing interpretation
Sonnet 4.6 is one of the best downgrade destinations from Opus 4.6 or GPT-5.4 when:
- The task is still real coding or analysis work
- Tool use still matters
- Quality still matters
- The hardest reasoning phase is already over

**Particularly attractive as:** the default implementation worker, the main subagent model, the first escalation above Haiku or Flash Lite. For many SE sessions, Sonnet 4.6 at `medium` effort should be the default, with escalation to Opus/GPT-5.4 only for genuinely hard turns.

---

### Claude Haiku 4.5

**Provider:** Anthropic | **Model ID:** `claude-haiku-4-5` | **Release:** October 15, 2025

#### What it is
Near-frontier performance with lightning-fast speed at Anthropic's most economical price point. Six months ago, this performance level would have been state-of-the-art. Designed as the ideal sub-agent in multi-agent architectures.

#### Intelligence & benchmarks
- **AA Intelligence Index:** 37 (reasoning); 31 (non-reasoning)
- **SWE-bench Verified:** 73.3%
- ~90% of Sonnet 4.5's performance on agentic coding evaluations
- Surpasses Claude Sonnet 4 on computer use tasks

#### Pricing
$1.00 / $5.00 per 1M tokens

#### Speed & latency
- **Reasoning:** 100.1 t/s, 12.62s TTFT
- **Non-reasoning:** 88.4 t/s
- 4–5x faster than Sonnet 4.5; millisecond-level on simple tasks

#### Thinking controls
Extended thinking via manual `budget_tokens` (up to 128K thinking budget). Does NOT use the newer 4.6-style adaptive-effort model. Routing logic should think in terms of "budgeted reasoning" rather than named effort levels. Binary: either allocate thinking budget or don't.

#### Context window
200K tokens (does not have 1M beta access)

#### SE-relevant strengths
- Full tool use and bash command support
- Enhanced computer use capabilities
- Ideal sub-agent in orchestrated workflows (Opus/Sonnet plans → Haiku executes)
- Strong at extraction, classification, and synthesis from existing context
- Cost: 1/5 of Sonnet, 1/25 of Opus per output token

#### Routing interpretation
**Use for:** cheap subagents, extracting facts from already-known context, classifying or labeling tasks, generating boilerplate, first-pass implementation, short reviews of narrow diffs, writing tests for already-decided fixes, commit message generation, log triage with clear stack traces, project status formatting, documentation generation from settled technical facts.

**Avoid for:** subtle architecture tradeoffs, novel failure analysis, high-risk code review, tasks requiring 1M context, security-sensitive decisions.

---

### Gemini 3.1 Pro Preview

**Provider:** Google DeepMind | **Model ID:** `gemini-3.1-pro` | **Release:** February 19, 2026

#### What it is
Google's smartest current model. Tied with GPT-5.4 at the top of the AA Intelligence Index. Supports text, image, speech, and video input. Uses extended thinking / chain-of-thought reasoning. #2 on Arena.ai (Elo 1500).

#### Intelligence & benchmarks
- **AA Intelligence Index:** 57 (tied for top)
- **ARC-AGI-2:** 77.1% (more than 2x improvement over Gemini 3 Pro)
- **GPQA Diamond:** 94.3% (highest score ever reported on this graduate-level science benchmark)

#### Pricing
| Condition | Input ($/1M) | Output ($/1M) |
|-----------|-------------|--------------|
| Standard | $2.00 | $12.00 |
| >200K context | $4.00 | $18.00 |

Context caching can reduce costs by up to 75% for repeated contexts.

#### Speed & latency
- **Output:** 111.6 t/s (fast once streaming begins)
- **TTFT:** 27.35s (high — problematic for interactive agent loops)

#### Context window
1M input, 64K output (note: output limit is lower than other frontier models at 128K)

#### Thinking controls
`thinkingLevel`: `low`, `high` (default: dynamic `high`). Google explicitly notes that Gemini 3.1 Pro **cannot fully disable thinking**. Less granular control than OpenAI (6 levels) or Anthropic (4 levels).

#### SE-relevant strengths
- Exceptional multimodal reasoning (text + image + audio + video)
- Strong at complex science and math reasoning
- Competitive pricing with context caching
- 1M context for large codebase analysis

#### SE-relevant limitations
- 64K output limit (vs 128K for Claude and GPT models)
- High TTFT makes it unsuitable for interactive agent loops
- Cannot fully disable thinking — minimum reasoning overhead always present
- Less granular effort control than competitors

#### Routing interpretation
Legitimate peer to GPT-5.4 for top-end planning. **Use when:** task is large-context and hard, multimodal reasoning matters, code and professional analysis are mixed, you can tolerate 27s wait for first token.

**Do not keep it on routine agent turns.** Its TTFT is much too high for chatter, formatting, or obvious execution steps. Better suited for batch/background planning tasks than interactive agent loops.

---

### Gemini 3.1 Flash Lite Preview

**Provider:** Google DeepMind | **Model ID:** `gemini-3.1-flash-lite` | **Release:** March 3, 2026

#### What it is
Google's fastest and most cost-efficient Gemini 3 model. Full multimodal support with 1M token context at budget pricing. 2.5x faster TTFT and 45% higher output speed than Gemini 2.5 Flash.

#### Intelligence & benchmarks
- **AA Intelligence Index:** 34
- **GPQA Diamond:** 86.9% (outperforms Gemini 2.5 Flash despite being the budget option)
- Strong instruction-following scores

#### Pricing
$0.25 / $1.50 per 1M tokens (one of the cheapest models in this analysis)

#### Speed & latency
- **Output:** 289.8–388.8 t/s depending on snapshot (extremely fast)
- **TTFT:** 5.18–6.46s (much better than Gemini 3.1 Pro)

#### Context window
1M tokens (largest context at this price point)

#### Thinking controls
`minimal`, `low`, `medium`, `high`. `minimal` is close to no-thinking but Google does not guarantee thinking is fully off.

#### SE-relevant strengths
- Full multimodal support (text, image, audio, video) at budget pricing
- Strong tool calling support, function calling, code execution, structured outputs
- 100% consistency in classification tasks (per Whering case study)
- 1M context at lowest price point — can hold entire codebases cheaply

#### SE-relevant limitations
- Does not support streaming function call arguments
- Not suitable for complex multi-step coding or debugging
- AA 34 intelligence means it will miss nuances that frontier models catch

#### Routing interpretation
One of the best downgrade targets in the entire set. **Use for:** high-volume subagent fan-out, extraction/classification/normalization, routine transformations, first-pass coding and UI generation, large batches of medium-difficulty work, log triage, repo exploration, project management formatting, content moderation.

**Do not use as final planner for:** hardest debugging, ambiguous multi-file architecture, high-stakes review, security-sensitive code.

---

### Cursor Composer 2

**Provider:** Cursor (Anysphere) | **Model ID:** `composer-2` (via Cursor platform) | **Release:** March 18, 2026

#### What it is
Cursor-native coding model using Mixture-of-Experts architecture. Designed for IDE operations: multi-file edits, precise diffs, codebase navigation, complex refactors. Uses RL to align expert routers with real developer workflows.

#### Intelligence & benchmarks (Cursor-reported)
- **SWE-bench Multilingual:** 73.7
- **Terminal-Bench 2.0:** 61.7
- **CursorBench:** 61.3

#### Pricing
| Tier | Input ($/1M) | Output ($/1M) |
|------|-------------|--------------|
| Standard | $0.50 | $2.50 |
| Fast variant | $1.50 | $7.50 |

86% cost reduction from Composer 1.5.

#### Real-world intelligence assessment
**Despite strong benchmark numbers, real-world consensus is that Composer 2 is less intelligent than GPT-5.4-class models for non-trivial tasks.** It excels at the specific operations it was trained for (multi-file edits, diffs, IDE-specific patterns) but falls behind frontier generalist models on:
- Complex debugging recovery
- Architectural reasoning
- Novel problem-solving
- Tasks requiring broad knowledge beyond coding patterns

#### Routing interpretation
Treat as a **Tier B specialized coding worker** — not a Tier A planner. Relevant mainly if the harness being analyzed is Cursor or Composer-like. Not a generic replacement for frontier models in arbitrary enterprise or SE sessions.

If the downstream router sees Cursor-specific traces, Composer 2 is closer to "default coding worker" than to "deep planner."

---

## Cost Efficiency Rankings

### Blended cost (3:1 input:output ratio, per 1M tokens)

1. **Gemini 3.1 Flash Lite** — ~$0.56/M
2. **Composer 2** — ~$1.00/M (Cursor-only)
3. **Claude Haiku 4.5** — ~$2.00/M
4. **Gemini 3.1 Pro** — ~$4.50/M
5. **GPT-5.3-Codex** — ~$4.81/M
6. **GPT-5.4** — ~$5.63/M
7. **Claude Sonnet 4.6** — ~$6.00/M
8. **Claude Opus 4.6** — ~$10.00/M

*GPT-5.3-Codex-Spark excluded due to no public API pricing.*

### Cost multipliers relative to cheapest (Flash Lite)

| Model | Cost Multiplier |
|-------|----------------|
| Gemini 3.1 Flash Lite | 1.0x |
| Composer 2 | 1.8x |
| Claude Haiku 4.5 | 3.6x |
| Gemini 3.1 Pro | 8.0x |
| GPT-5.3-Codex | 8.6x |
| GPT-5.4 | 10.1x |
| Claude Sonnet 4.6 | 10.7x |
| Claude Opus 4.6 | 17.9x |

---

## Thinking Effort Controls: Cross-Provider Comparison

| Provider | Model(s) | Effort Levels | Key Notes |
|----------|----------|---------------|-----------|
| **OpenAI** | GPT-5.4, GPT-5.3-Codex | `none`, `low`, `medium`, `high`, `xhigh` | Most granular (6 levels); `none`/`low` ideal for fast worker mode |
| **Anthropic** | Opus 4.6 | `low`, `medium`, `high`, `max` | `max` is Opus-only; at `medium`, matches Sonnet 4.5 SWE-bench with 76% fewer output tokens |
| **Anthropic** | Sonnet 4.6 | `low`, `medium`, `high` | No `max`; `medium` recommended as default; strong even with thinking disabled |
| **Anthropic** | Haiku 4.5 | Manual `budget_tokens` (up to 128K) | No named levels; binary on/off with budget control |
| **Google** | Gemini 3.1 Pro | `low`, `high` | Cannot fully disable thinking; less developer control |
| **Google** | Gemini 3.1 Flash Lite | `minimal`, `low`, `medium`, `high` | `minimal` ≈ near-no-thinking (not guaranteed) |
| **OpenAI** | GPT-5.3-Codex-Spark | Not configurable | Fixed latency-first behavior |

### Key routing insight
Thinking effort is one of the most powerful levers for cost optimization. **Always consider adjusting effort level before switching models.** A frontier model at low/medium effort can often handle routine tasks as well as a mid-tier model at full effort — while preserving instruction-following patterns and tool-calling compatibility. Model-switching introduces compatibility risks (different tool-call formats, different instruction-following quirks, different error patterns).

---

## Suggested Tiering For Session Analysis

### Tier A: Frontier Planners
Use for hard reasoning, architecture, recovery, review, complex analysis.

- **GPT-5.4** (`high`/`xhigh`)
- **Gemini 3.1 Pro Preview**
- **Claude Opus 4.6** (`high`/`max`)

### Tier B: Strong Workers
Use for implementation, standard coding, document analysis, tool-heavy workflows.

- **Claude Sonnet 4.6** (`medium`/`high`)
- **GPT-5.3-Codex**
- **Composer 2** (Cursor-only)

### Tier C: Efficient Workers
Use for bounded subtasks, extraction, classification, light coding, PM tasks.

- **Claude Haiku 4.5**
- **Gemini 3.1 Flash Lite**

### Tier D: Ultra-Fast Specialists
Use for latency-critical interactive coding loops.

- **GPT-5.3-Codex-Spark** (limited availability)

---

## Practical Routing Heuristics For Harness Logs

### Keep frontier models (Tier A) on these segments

- Initial problem framing when the task is ambiguous
- Planning across many tools or files
- Hard root-cause analysis after earlier failure
- Final review before merge or deploy
- Large-context synthesis (reasoning over >100K tokens of code/docs)
- Multimodal reasoning (screenshots, diagrams, UI mockups)
- Computer-use steps where wrong actions are expensive
- Security-sensitive code changes
- Complex document analysis requiring cross-reference reasoning
- Architectural decisions with long-term implications

### Shift to Tier B (strong workers) on these segments

- Feature implementation under a known plan
- Standard code generation and editing
- Tool-calling workflows with clear parameters
- Document comprehension and extraction (Sonnet matches Opus on OfficeQA)
- Test writing for well-understood behavior
- Code review of straightforward changes
- Sprint planning and task breakdown
- Multi-file changes with clear patterns

### Shift to Tier C (efficient workers) on these segments

- "I'm going to inspect X/Y/Z" — simple grep, search, file listing
- Summarizing obvious findings from tool output
- Converting notes into a checklist
- Making a requested naming or formatting change
- Applying a straightforward patch after the bug is understood
- Writing repetitive tests for an already-decided fix
- Summarizing logs with clear stack traces
- Drafting docs from already-settled technical facts
- Emitting status updates to the user
- Commit message generation
- Log triage and error classification
- Boilerplate code generation
- Project management formatting and updates

### Shift to Tier D (ultra-fast) when available

- Quick file edits during interactive pairing
- Patch generation after the fix is already understood
- Repeated small implementation steps
- Code cleanup and formatting
- Short feedback loops with a human actively steering

### Red flags that a segment should NOT be downgraded

- The model is actively recovering from two or more failed hypotheses
- The turn depends on integrating many tool outputs at once
- The task requires deciding what NOT to change, not just what to change
- The user request is underspecified and the model must infer hidden constraints
- The model is reviewing code for subtle regressions
- The turn touches security, correctness, or deployment risk
- The context window is nearly full and coherent long-range reasoning is needed
- The model needs to coordinate multiple parallel agent subtasks

---

## Downgrade Ladders

### If current segment is on GPT-5.4 or Gemini 3.1 Pro:
1. First try reducing effort level (`xhigh` → `medium` or `low`) before switching models
2. Downgrade to Claude Sonnet 4.6 (`medium` or `low`) or GPT-5.4 (`low`/`none`) for still-important implementation work
3. Downgrade further to Claude Haiku 4.5 or Gemini 3.1 Flash Lite for narrow, bounded, high-throughput tasks
4. For latency-critical interactive coding, downgrade to GPT-5.3-Codex-Spark where available

### If current segment is on Claude Opus 4.6:
1. First try reducing effort (`max` → `medium`) — at `medium`, Opus matches Sonnet 4.5 SWE-bench with 76% fewer output tokens
2. Move most execution turns to Claude Sonnet 4.6
3. Move clearly bounded subagent or transform tasks to Haiku 4.5

### If current segment is on Claude Sonnet 4.6:
1. First try reducing effort (`high` → `low`)
2. Move extraction, classification, and simple coding to Haiku 4.5
3. Move high-volume simple tasks to Flash Lite

---

## Condensed Decision Rules

Use this as a compact rubric for the downstream routing LLM:

1. **If the turn is mostly planning, architecture, rescue, or review** → stay Tier A frontier
2. **If the turn is mostly execution under a known plan** → move to Tier B (or reduce effort on current Tier A model)
3. **If the turn is extraction, normalization, search triage, formatting, or shallow implementation** → move to Tier C
4. **If the turn is human-interactive coding where latency dominates** → prefer Tier D (Spark) or Tier C (Haiku/Flash Lite)
5. **If the current frontier model is spending very long TTFT before visible output** → that is a strong signal that similar routine turns are overpriced for the value they add
6. **When in doubt, reduce thinking effort before switching models** — lower risk, same API endpoint, preserves tool-calling patterns

---

## Final Takeaway

For harness-log analysis, the biggest practical mistake is using a single frontier model at full reasoning effort across the whole session. Most sessions contain a small number of genuinely frontier-worthy turns and a much larger number of execution, extraction, formatting, and status turns that can be shifted down safely.

If forced to summarize the routing strategy in one sentence:

**Use GPT-5.4 or Gemini 3.1 Pro for hard planning, Opus for the highest-stakes decisions, Sonnet for high-quality execution, Haiku or Flash Lite for cheap bounded work, and Spark for ultra-fast interactive coding when available.**

---

## Sources

### Primary release / vendor documentation
- OpenAI, "Introducing GPT-5.3-Codex-Spark" — https://openai.com/index/introducing-gpt-5-3-codex-spark/
- OpenAI, "Introducing GPT-5.4" — https://openai.com/index/introducing-gpt-5-4/
- OpenAI, "Introducing GPT-5.4 mini and nano" — https://openai.com/index/introducing-gpt-5-4-mini-and-nano/
- OpenAI API guide — https://developers.openai.com/api/docs/guides/latest-model
- Anthropic, "Claude Opus 4.6" — https://www.anthropic.com/news/claude-opus-4-6
- Anthropic, "Claude Sonnet 4.6" — https://www.anthropic.com/news/claude-sonnet-4-6
- Anthropic, "Claude Haiku 4.5" — https://www.anthropic.com/news/claude-haiku-4-5
- Anthropic model selection docs — https://platform.claude.com/docs/en/about-claude/models/choosing-a-model
- Anthropic pricing docs — https://platform.claude.com/docs/en/about-claude/pricing
- Anthropic extended thinking docs — https://platform.claude.com/docs/en/build-with-claude/extended-thinking
- Anthropic effort docs — https://platform.claude.com/docs/en/build-with-claude/effort
- Cursor, "Introducing Composer 2" — https://cursor.com/blog/composer-2
- Google, "Gemini 3.1 Pro" — https://blog.google/innovation-and-ai/models-and-research/gemini-models/gemini-3-1-pro/
- Google, "Gemini 3.1 Flash-Lite" — https://blog.google/innovation-and-ai/models-and-research/gemini-models/gemini-3-1-flash-lite/
- Google Gemini pricing — https://ai.google.dev/gemini-api/docs/pricing
- Google DeepMind model card — https://deepmind.google/models/model-cards/gemini-3-1-pro/

### Comparison and benchmark sources
- Artificial Analysis model leaderboard — https://artificialanalysis.ai/models
- Artificial Analysis model-specific pages for GPT-5.4, GPT-5.3-Codex, Claude Opus 4.6, Claude Sonnet 4.6, Claude Haiku 4.5, Gemini 3.1 Pro Preview, and Gemini 3.1 Flash-Lite Preview
- Codex 5.3 vs. Codex Spark speed vs. intelligence comparison — https://www.turingcollege.com/blog/codex-5-3-vs-codex-spark-speed-vs-intelligence
- GPT-5.4 vs GPT-5.3-Codex comparison — https://www.nxcode.io/resources/news/gpt-5-4-vs-gpt-5-3-codex-upgrade-comparison-2026
- GPT-5.4 mini and nano benchmarks — https://www.datacamp.com/blog/gpt-5-4-mini-nano
- Cursor Composer 2 review — https://www.buildfastwithai.com/blogs/cursor-composer-2-review-2026
- Frontier model comparison (March 2026) — https://medium.com/@Micheal-Lanham/the-march-2026-frontier-gpt-5-4-vs-gemini-3-1-vs-claude-4-6-daebf22e672e
