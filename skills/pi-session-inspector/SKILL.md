---
name: pi-session-inspector
description: "Inspect local pi-coding-agent session logs under ~/.pi/agent: session JSONL, the recorder.db analytics cache, token/cost usage, tool usage + failures, turn/iteration durations, model breakdown, subagent inspection, date filters, and jq/SQL recipes for pi session analysis."
---

# Pi Session Inspector

## Overview

Use this skill to inspect persisted pi-coding-agent (`@earendil-works/pi-coding-agent`) session logs on the local machine.
Session logs are newline-delimited JSON (`.jsonl`) files stored per-project under `~/.pi/agent/sessions/`.
Each session file is a flat sequence of heterogeneous records keyed by a `type` field.

pi also ships an analytics cache: the `recorder` extension (from the `git:github.com/aldoborrero/pi-agent-kit` package) writes `~/.pi/agent/recorder.db` **live** from runtime events. This skill keeps the same contract as its sibling inspectors — **raw JSONL is the source of truth** — with one pi-specific consequence: pi already maintains the derived SQLite cache itself, so this skill installs **no Stop hook and builds no second cache**. It reads `recorder.db` **read-only** as an optional accelerator and as the only source of two metrics the JSONL cannot provide (precise per-turn / per-tool `duration_ms`, and turn/iteration grouping). Every core workflow works from JSONL alone when `recorder.db` is absent.

Compared with Claude session logs and Codex rollouts, pi session logs line up on many analysis tasks but not on identical fields:
- Token usage is summed from **per-message** `assistant.message.usage` (not deduplicated by `requestId`, not cumulative snapshots). Each assistant message is exactly one API response.
- **Cost is pi-computed and embedded** in `usage.cost.total` (and aggregated into `recorder.db`). No repricer is needed or shipped; for local providers (LM Studio, MLX) cost is `0`.
- Tool usage comes from `assistant.message.content[].type=="toolCall"` blocks; tool failures are first-class via `toolResult.isError` (no `tool_use.id`↔`tool_result` correlation needed).
- Logical turns/iterations and their durations come from `recorder.db` (`turns.turn_index` / `iteration_number` / `duration_ms`), which are derived from runtime `turn_start`/`turn_end` events — they are **not** present in the JSONL.
- Subagent inspection comes from the parent session's `subagent` toolResult `details.results[]`; pi subagents are spawned as separate `pi --no-session` subprocesses and write **no child JSONL**.
- Session naming is the slugified cwd directory plus the session `cwd`; there is no `slug`/`custom-title`/`thread_name` record.
- PR links are not first-class; extract GitHub PR URLs from message and tool-output text.

## Log Kinds

- Session conversation logs (source of truth):
  - `~/.pi/agent/sessions/{slug}/{ISO-timestamp}_{session-uuid}.jsonl`
  - The slug is the session cwd with path separators replaced by `-`, dots preserved, wrapped in double dashes — e.g. `/Users/me/code/github.com/org/repo` → `--Users-me-code-github.com-org-repo--`.
  - The filename timestamp uses dashes in the time portion (`2026-06-08T17-02-28-913Z`); the session `id` (a UUID) is the suffix.
  - Complete conversation replay: user messages, assistant responses, tool calls/results, model/thinking changes, context injections, compaction events.
  - These are the primary target for analysis.
- Derived analytics cache (optional, read-only):
  - `~/.pi/agent/recorder.db` (plus `recorder.db-wal` / `recorder.db-shm` in WAL mode) and Datasette metadata `~/.pi/agent/recorder-metadata.yml`.
  - Maintained live by the `recorder` extension. Tables: `sessions`, `turns`, `tool_calls`, `messages`, `model_changes`; views: `v_session_summary`, `v_tool_stats`, `v_daily_cost`.
  - Always open it read-only. It is the user's live database; never write to it or checkpoint it.
- Subagent definitions:
  - `~/.pi/agent/agents/*.md` — user-level agent roles (Markdown + YAML frontmatter `name`/`description`/`model`/`tools`). The skill reports these but they are definitions, not logs.
- Prompts / slash commands:
  - `~/.pi/agent/prompts/*.md` — registered as slash commands; not session logs.
- Settings:
  - `~/.pi/agent/settings.json` — default provider/model, enabled packages/extensions.

## Record Types

Verified across the live corpus (newline-delimited JSON, one object per line, keyed by `type`):

| Type | Count* | Description | Key Fields |
|------|-------:|-------------|------------|
| `message` | 1815 | User / assistant / tool-result message | `message` (with `role`, `content[]`, `timestamp`, and role-specific fields), `id`, `parentId`, `timestamp` |
| `model_change` | 97 | Model in effect / model switch | `provider`, `modelId`, `id`, `parentId`, `timestamp` |
| `custom` | 84 | Extension UI/state snapshot | `customType` (`plan-mode`, `plannotator`), `data`, `id`, `parentId`, `timestamp` |
| `thinking_level_change` | 82 | Reasoning effort change | `thinkingLevel` (`off`/`medium`/…), `id`, `parentId`, `timestamp` |
| `session` | 73 | Session root metadata | `version` (format version, e.g. `3`), `id` (session UUID), `cwd`, `timestamp` |
| `custom_message` | 22 | Injected context message | `customType` (`pi-memory-context`, `plan-mode-context`, `plan-execution-context`, `plan-mode-execute`, `plan-todo-list`, `interactive-shell-transfer`), `content`, `display`, `details?`, `id`, `parentId`, `timestamp` |
| `compaction` | 3 | Context-window compaction event | `summary`, `tokensBefore`, `firstKeptEntryId`, `fromHook`, `details` (`readFiles`/`modifiedFiles`), `id`, `parentId`, `timestamp` |

\* Counts are from one machine's corpus, illustrating relative frequency, not a contract. `custom_message` and `compaction` were discovered by reading live files; treat the type set as open and tolerate new types.

## Format Stability

pi session JSONL carries an explicit integer format version on the `session` record (`version: 3` in all observed sessions) — unlike Claude (no version) and Codex (no embedded schema version). Treat it as the format-generation hint. There is no published stability contract; pi is pre-1.0 and the format can change between releases.

This skill was developed and verified against:
- pi core `@earendil-works/pi-coding-agent` **0.79.0**
- session format `version: 3`
- `recorder` extension **1.0.0** (`better-sqlite3 ^11.8.1`)

Parser resilience strategy (mirrors the sibling inspectors):
- Key on the top-level `type` field and `message.role` as the primary discriminators.
- Defensive `.get()` access with fallbacks for every field — never assume a field exists.
- Tolerate unknown record types, unknown `customType`s, and additive fields without failing.
- The session `version` is the closest proxy for format generation; re-verify field shapes against live files after a pi upgrade.

## Record Structure

Like Codex but unlike Claude, pi wraps each message in an envelope (`{type:"message", id, parentId, timestamp, message:{…}}`); however non-message records (`session`, `model_change`, etc.) are **flat** with their own top-level keys. Records form a chain via `parentId` → `id` (short hex ids; the `session` record's `id` is the full UUID). The `session` record is the root.

**Timestamps:** JSONL timestamps are ISO-8601 strings at message time (`"2026-06-08T17:02:28.913Z"`). `recorder.db` timestamps are Unix **milliseconds** recorded with `Date.now()` at event time. Do not treat `recorder.db` timings as message timestamps.

### Session metadata

From the `session` record: `id` (canonical UUID, matches the filename suffix and `recorder.db` `sessions.id`), `cwd`, `version` (format version), `timestamp`. The initial model comes from the first `model_change` (`provider`/`modelId`); the initial thinking level from the first `thinking_level_change`.

### Message roles

`message.role` is one of:
- `user` — `content[]` of `text` blocks. The first `user` message is the session prompt.
- `assistant` — `content[]` of `text` / `thinking` / `toolCall` blocks, plus `model`, `provider`, `responseId`, `responseModel`, `stopReason`, `usage`.
- `toolResult` — `toolName`, `toolCallId`, `isError` (boolean), `content[]` (`text`), and an optional `details` object (carries rich tool-specific data, e.g. the subagent breakdown).

### Assistant content blocks

- `{"type":"text","text":"…"}` — text response.
- `{"type":"thinking","thinking":"…"}` — chain-of-thought.
- `{"type":"toolCall","id":"…","name":"bash","arguments":{…}}` — tool invocation. Tool name is `name`; input is `arguments`. (pi tool names are lowercase: `bash`, `read`, `edit`, `grep`, `ls`, `write`, `find`, `ast_grep`, `subagent`, `web_fetch`, `memory_search`, …)

### Token usage and cost

Each `assistant` record carries `message.usage`:
- `input`, `output`, `cacheRead`, `cacheWrite`, `totalTokens`
- `cost`: `{input, output, cacheRead, cacheWrite, total}` — pi-computed USD. `0` for local providers.

Sum these across `assistant` messages for session totals. `cacheRead`/`cacheWrite` are JSONL-only; `recorder.db` does not store cache tokens.

### `stopReason`

Observed values: `stop`, `toolUse`, `aborted`, `length`, `error`, and `null`. (`recorder-metadata.yml`'s illustrative `"end_turn, tool_use"` example does **not** match pi's actual values — pi uses `stop`/`toolUse`.)

### Subagents

The `subagent` tool spawns a separate `pi … --no-session` subprocess per agent, so subagents write **no child session JSONL**. Their execution detail is streamed back to the parent and persisted in the parent's `subagent` `toolResult.details`:
- `details.mode` — `single` / `parallel` / `chain`
- `details.results[]` — one entry per agent, each with `agent`, `agentSource`, `task`, `exitCode`, `model`, `stopReason`, `usage` (`input`/`output`/`cacheRead`/`cacheWrite`/`cost`/`contextTokens`/`turns`), `messages[]` (the subagent's own turns, including its `toolCall`s), `stderr`, `errorMessage`, `step`.

This is the **sole clean** subagent source. `recorder.db` corroborates: a successful subprocess appears as a `sessions` row with `session_file = NULL` (the recorder extension still fires under `--no-session`), temporally adjacent to the parent's `subagent` tool_call — but in `parallel` mode multiple concurrent subprocesses make time-attribution ambiguous, so it is corroboration only, not a parent link. **Only single-mode subagent runs were observed in the live corpus; the parallel/chain `results[]` array shape is inferred from the extension source (`subagent/index.ts`).**

## Workflow

1. Locate the pi state root (`~/.pi/agent/`), the sessions directory, and whether `recorder.db` is present.
2. Identify which project(s)/session(s) the user wants to inspect.
3. Start with a summary:
   - Session metadata (cwd, format version, model, thinking level) from the `session`/`model_change` records
   - First user message
   - Record counts by type
   - Token usage and pi-computed cost, summed per-message, broken down by model
   - Tool usage and per-tool `isError` failure counts
   - Stop-reason distribution
   - Context injections (`custom` / `custom_message`) and compaction events
   - Subagent overview from `subagent` toolResult details
   - Precise turn/iteration and tool durations from `recorder.db` when a matching row exists
4. Use targeted extraction:
   - `scripts/inspect_session.py` for repeatable local parsing (verbs below)
   - `jq` for quick JSONL inspection
   - `sqlite3 … "file:~/.pi/agent/recorder.db?mode=ro"` (read-only) for cache-backed aggregates
   - `uv run --python 3.14 python3 - <<'PY'` for ad hoc Python snippets

## Quick Start

- Locate roots, recorder.db state, and subagent definitions:
  - `uv run --python 3.14 scripts/inspect_session.py locate`
- List recent sessions across all projects:
  - `uv run --python 3.14 scripts/inspect_session.py list --since 2026-06-01 --limit 20`
- List sessions for a specific project:
  - `uv run --python 3.14 scripts/inspect_session.py list --project KidStrongBedrock --limit 10`
- Summarize the newest session:
  - `uv run --python 3.14 scripts/inspect_session.py summary`
- Summarize a specific session by path or session id:
  - `uv run --python 3.14 scripts/inspect_session.py summary <path-or-session-id>`
- Summarize using the ingestion profile (`session_inspector_v2`):
  - `uv run --python 3.14 scripts/inspect_session.py --profile ingestion summary <path-or-session-id>`
- List using the ingestion profile:
  - `uv run --python 3.14 scripts/inspect_session.py --profile ingestion list --limit 10`
- Print raw matching records:
  - `uv run --python 3.14 scripts/inspect_session.py records <path-or-session-id> --record-type message --role toolResult --tool-name bash --tail 10`
- Inspect subagent invocations for a session:
  - `uv run --python 3.14 scripts/inspect_session.py subagents <path-or-session-id>`

Global flags precede the subcommand (e.g. `inspect_session.py --json summary <id>`, `inspect_session.py --profile ingestion list`). `summary`, `records`, and `subagents` accept a session id (full or prefix) or a `.jsonl` path. Use `--pi-home` to point at a non-default state root.

## Parsing Guidance

- The `session` record (`parentId` absent) is the root; read `id`/`cwd`/`version` from it.
- Resolve the initial model from the **first** `model_change` (`provider`/`modelId`); later `model_change` records are mid-session switches. The per-model token breakdown should come from each `assistant` message's own `model`, which can differ from the session's initial `model_change`.
- Token totals are **summed per assistant message** — there is no cross-request dedup key. Each assistant message is one API call (`api_calls_exact` = assistant message count).
- Cost is read directly from `usage.cost.total`; do not reprice. It is `0` for local providers; cloud providers populate it.
- Tool invocations come from `toolCall` blocks (`name`/`arguments`); failures come from `toolResult.isError`. Correlate `toolResult.toolCallId` back to the `toolCall.id` only if you need to attribute a failure to its arguments.
- `toolResult.toolName == "subagent"` records carry the subagent breakdown in `details.results[]`. Treat the array as the authoritative per-agent source; treat `recorder.db` NULL-`session_file` rows as corroboration only.
- `recorder.db` is opened read-only and joined on `sessions.id == <session uuid>`. Prefer it for precise `turns`/`tool_calls` `duration_ms` and turn/iteration grouping; fall back to JSONL (no turn boundaries; durations unavailable) when no row matches or the DB is absent.
- `recorder.db` turn coverage can be **partial** for a session — the recorder extension only captures turns that occurred while it was loaded, so a session may show fewer `turns` rows than the JSONL has assistant responses (e.g. the extension was enabled mid-session). Treat the JSONL assistant-response count as the authoritative API-call count; use `recorder.db` turns for durations of the turns it did capture.
- `list`, `summary`, `records`, and `subagents` all work from JSONL alone. `recorder.db` only adds durations and faster session-level aggregates.
- Tolerate additive fields and unknown `type`/`customType`/`stopReason` values — the format evolves.

## Analysis (recorder.db)

`recorder.db` is the existing derived analytics cache. Query it **read-only**. Timestamps are Unix milliseconds.

Schema (verified):

| Table | Purpose | Key columns |
|------|---------|------------|
| `sessions` | One row per session (token/cost rollup) | `id`, `session_file` (NULL for subagent subprocesses), `cwd`, `started_at`, `ended_at`, `model_provider`, `model_id`, `total_input_tokens`, `total_output_tokens`, `total_cost` |
| `turns` | One row per LLM response **iteration** | `session_id`, `turn_index`, `iteration_number`, `started_at`, `ended_at`, `duration_ms`, `model_id`, `input_tokens`, `output_tokens`, `cost`, `stop_reason` |
| `tool_calls` | One row per tool invocation | `id`, `session_id`, `turn_id`, `tool_name`, `input_json` (≤50KB), `started_at`, `ended_at`, `duration_ms`, `is_error`, `result_text` (≤50KB) |
| `messages` | User + assistant message text (≤50KB) | `session_id`, `role`, `content`, `turn_id`, `timestamp` |
| `model_changes` | Mid-session model switches | `session_id`, `timestamp`, `source` (`set`/`cycle`/`restore`), `from_*`, `to_*` |

Views: `v_session_summary`, `v_tool_stats`, `v_daily_cost`.

**recorder.db gaps vs. JSONL** (read JSONL for these): no cache tokens (`cacheRead`/`cacheWrite` dropped), no thinking-block metrics, no `compaction`/`custom_message` context events, no subagent parent link, text truncated at 50KB. Conversely, **JSONL lacks** precise per-turn/per-tool `duration_ms` and turn/iteration grouping — those exist only in `recorder.db`.

Open it read-only:

```sh
sqlite3 "file:$HOME/.pi/agent/recorder.db?mode=ro" ".tables"
```

Daily cost and tokens:

```sql
SELECT date(started_at/1000,'unixepoch','localtime') AS day,
       count(*) AS sessions,
       sum(total_input_tokens) AS input_tokens,
       sum(total_output_tokens) AS output_tokens,
       round(sum(total_cost),4) AS cost
FROM sessions GROUP BY day ORDER BY day DESC;
```

Tool usage and error rate (lowercase pi tool names):

```sql
SELECT tool_name, count(*) AS calls, sum(is_error) AS errors,
       round(100.0*sum(is_error)/count(*),1) AS error_pct,
       round(avg(duration_ms)) AS avg_ms, max(duration_ms) AS max_ms
FROM tool_calls GROUP BY tool_name ORDER BY calls DESC;
```

Model token/cost breakdown per turn:

```sql
SELECT model_provider, model_id, count(*) AS iterations,
       sum(input_tokens) AS input_tokens, sum(output_tokens) AS output_tokens,
       round(sum(cost),4) AS cost, round(avg(duration_ms)) AS avg_turn_ms
FROM turns WHERE model_id IS NOT NULL
GROUP BY model_provider, model_id ORDER BY cost DESC;
```

Subagent subprocess rows (NULL `session_file` — corroboration only):

```sql
SELECT id, datetime(started_at/1000,'unixepoch','localtime') AS started,
       model_id, total_input_tokens, total_output_tokens
FROM sessions WHERE session_file IS NULL ORDER BY started_at;
```

Read:Edit ratio by day:

```sql
SELECT date(t.started_at/1000,'unixepoch','localtime') AS day,
       sum(tc.tool_name='read') AS reads,
       sum(tc.tool_name='edit') AS edits,
       round(CAST(sum(tc.tool_name='read') AS REAL)/nullif(sum(tc.tool_name='edit'),0),2) AS read_edit_ratio
FROM tool_calls tc JOIN turns t ON t.id = tc.turn_id
GROUP BY day ORDER BY day;
```

## Resources

### scripts/

- `scripts/inspect_session.py`
  - Local Python 3.14 CLI (stdlib only) for locating, listing, summarizing, filtering, and inspecting pi session logs and subagent activity.
  - Reads raw JSONL (source of truth) and `recorder.db` (read-only accelerator + duration source).
  - Run with `uv run --python 3.14`.

### references/

- `references/recipes.md`
  - `jq` recipes for JSONL extraction
  - read-only `sqlite3` recipes against `recorder.db`
  - `uv` + Python 3.14 one-off snippets
  - field-level guidance for pi session records, including token/cost, tool failures, durations, and subagent extraction
