---
name: claude-session-inspector
description: "Inspect local Claude Code session logs under ~/.claude: project JSONL, subagent logs, history, metadata, saved sessions, token/tool usage, turns/events, delegation, date filters, and jq/Python recipes for Claude session analysis."
---

# Claude Session Inspector

## Overview

Use this skill to inspect persisted Claude Code session logs on the local machine.
Session logs are JSONL files stored per-project under `~/.claude/projects/`.
Each session file is a flat sequence of heterogeneous records keyed by a `type` field.
The inspector now keeps a derived SQLite cache at `~/.claude/inspector/session_inspector.db`. Raw JSONL remains the source of truth.

Compared with Codex rollout logs, Claude session logs line up on many analysis tasks but not on identical underlying fields:
- Token usage can be deduplicated exactly by `requestId`.
- Tool usage is extracted from `assistant.message.content[].type=="tool_use"` blocks.
- Logical turns can be reconstructed statelessly by grouping streamed `assistant` chunks on `message.id`.
- Tool failures can be reconstructed statelessly by correlating `tool_use.id` with later `user.message.content[].type=="tool_result"` blocks.
- Subagent inspection uses `subagents/agent-*.jsonl` files under a parent session directory, not separate child rollout threads. Discovery recurses: direct subagents live at `subagents/agent-*.jsonl`, and nested workflow subagents at `subagents/workflows/<wf>/agent-*.jsonl` (the workflow `journal.jsonl` and `agent-*.meta.json` sidecars are skipped). Nested agent ids are path-qualified (`workflows/<wf>/<hex>`) so two workflow runs cannot collide on a reused agent-id hex.
- Session naming comes from `custom-title`, `agent-name`, and `slug`, not a separate session index.
- PR links are first-class `pr-link` records.

## Log Kinds

- Session conversation logs:
  - `~/.claude/projects/{project-path}/{session-uuid}.jsonl`
  - Complete conversation replay: user messages, assistant responses, tool results, system events.
  - These are the primary target for analysis.
- Subagent logs:
  - `~/.claude/projects/{project-path}/{session-uuid}/subagents/agent-{agent-id}.jsonl`
  - Contain only `user` and `assistant` records for delegated agent work.
- Global input history:
  - `~/.claude/history.jsonl`
  - Append-only log of user inputs across all sessions. Not full session replay.
- Session metadata (active only):
  - `~/.claude/sessions/{pid}.json`
  - Ephemeral metadata for currently running sessions. Not useful for historical analysis.

## Record Types

Claude Code session files contain these record types:

| Type | Description | Key Fields |
|------|-------------|------------|
| `user` | User message or tool result | `message`, `uuid`, `parentUuid`, `cwd`, `sessionId`, `version`, `gitBranch`, `slug`, `permissionMode`, `toolUseResult` (when returning tool output) |
| `assistant` | Claude response | `message` (full API response with `content[]`, `model`, `usage`, `stop_reason`), `requestId` |
| `progress` | Hook/subagent progress | `data` (nested progress payload), `toolUseID`, `parentToolUseID` |
| `file-history-snapshot` | File state for undo | `messageId`, `snapshot` (tracked file backups), `isSnapshotUpdate` |
| `system` | Session events | `subtype` (`turn_duration`, `local_command`), `durationMs`, `content` |
| `last-prompt` | Resume marker | `lastPrompt`, `sessionId` |
| `pr-link` | PR metadata | `prNumber`, `prUrl`, `prRepository` |
| `queue-operation` | Background tasks | `operation` (`enqueue`/`dequeue`/`complete`), `content` |
| `custom-title` | Session title | `customTitle`, `sessionId` |
| `agent-name` | Agent name | `agentName`, `sessionId` |

## Format Stability

The session JSONL format has no documented schema, no version identifier, and no stability contract from Anthropic. The `version` field in session records (e.g., `2.1.92`) is the Claude Code application version, not a log format version. Format changes ship silently with application updates — no changelog, no migration path, no deprecation notice. The only direct schema documentation request (anthropics/claude-code#27724) was auto-closed with no response.

Known historical breakages include: `/resume` silently excluding pre-v2.1.37 sessions after a version filter was added (anthropics/claude-code#24536), auto-updates deleting JSONL files (anthropics/claude-code#36272), and new record types (`queue-operation`, `compact_boundary`) appearing without notice.

The parser's resilience depends on:
- Keying on the `type` field as the primary discriminator (stable so far).
- Defensive `get()` access with fallbacks for every field — never assume a field exists.
- Tolerating unknown record types and additive fields without failing.
- `rebuild` as the recovery path when parser logic is updated for format changes.
- The Claude Code app version as the closest proxy for format generation, though it does not map to documented schema changes.

This skill was developed and tested against Claude Code **v2.1.92–v2.1.111** (2026-04-07 through 2026-04-16). Sessions from v2.1.78 through v2.1.111 have been verified to parse correctly. Server-side tool tracking (advisor, web_search, code_execution) was added against v2.1.92+ logs. When updating the parser after a format change, test against sessions from multiple app versions. Do not assume the change was announced or documented.

## Record Structure

Unlike Codex rollout logs (which use a uniform `{timestamp, type, payload}` envelope), Claude Code records are **flat** with varying top-level keys per type. The `type` field is the only universal discriminator.

### Session Metadata

There is no explicit `session_meta` record. Session metadata is embedded in the **first `user` record** (where `parentUuid` is `null`):
- `sessionId`: Canonical session UUID
- `cwd`: Working directory at session start
- `version`: Claude Code version
- `gitBranch`: Git branch at session start
- `permissionMode`: Permission mode (`plan`, `bypassPermissions`, etc.)
- `entrypoint`: How the session was launched (`cli`, etc.)

The `slug` field (human-readable name like `"lucky-singing-sunset"`) appears on later records once generated.

### Message Threading

Records form a singly-linked chain via `parentUuid` -> `uuid`. The first user message has `parentUuid: null`. Tool results are `user` records with `toolUseResult` and `sourceToolAssistantUUID` fields.

### Assistant Content Blocks

Each `assistant` record's `message.content` is an array of typed blocks:
- `{"type": "text", "text": "..."}` — text response
- `{"type": "tool_use", "id": "...", "name": "ToolName", "input": {...}}` — client tool invocation
- `{"type": "thinking", "thinking": "...", "signature": "..."}` — chain-of-thought
- `{"type": "server_tool_use", "id": "srvtoolu_...", "name": "advisor", "input": {...}}` — server-side tool invocation (Anthropic-hosted)
- `{"type": "<name>_tool_result", "tool_use_id": "srvtoolu_...", "content": "..."}` — server-side tool result (e.g., `advisor_tool_result`, `web_search_tool_result`)

Server-side tools (`advisor`, `web_search`, `code_execution`) are executed by Anthropic servers, not the client. The invocation and result appear as sibling content blocks in the assistant message stream, often across different JSONL chunks sharing the same `message.id`. There is no client `user` record with a `tool_result` — the result arrives in the assistant stream.

### Token Usage

Each `assistant` record includes `message.usage` with:
- `input_tokens`, `output_tokens`
- `cache_creation_input_tokens`, `cache_read_input_tokens`
- `service_tier`, `speed`, `inference_geo`
- `iterations[]` — per-iteration token breakdown (present when server tools are used). Entries with `type: "<tool>_message"` (e.g., `advisor_message`) contain the server tool's own token cost and model.

## Workflow

1. Locate the Claude state root (`~/.claude/`) and the relevant project directory.
2. Identify which project(s) the user wants to inspect.
3. Start with a summary:
   - Session metadata from first user record
   - First user message text
   - Record counts by type
   - Logical turns reconstructed from streamed assistant chunks
   - Token usage deduplicated across API calls
   - Tool usage and per-tool error counts
   - Hook summary and turn durations from `system` records
   - Subagent overview (count, models used, delegated tasks)
4. Use targeted extraction:
   - `jq` for quick shell inspection
   - `scripts/inspect_session.py` for repeatable local parsing
   - `refresh` / `rebuild` when you need to backfill or repair the SQLite cache
   - `--profile ingestion` when downstream systems want the normalized `session_inspector_v2` contract
   - `uv run --python 3.14 python3 - <<'PY'` for ad hoc Python snippets

## Quick Start

- Locate root and latest files:
  - `uv run --python 3.14 scripts/inspect_session.py locate`
- Build or update the SQLite cache:
  - `uv run --python 3.14 scripts/inspect_session.py refresh`
- Reconcile delayed/pending Stop-hook imports without scanning all sessions:
  - `uv run --python 3.14 scripts/inspect_session.py refresh --pending`
- Rebuild the cache from raw logs:
  - `uv run --python 3.14 scripts/inspect_session.py rebuild`
- List recent sessions across all projects:
  - `uv run --python 3.14 scripts/inspect_session.py list --since 2026-03-15 --limit 20`
- List sessions for a specific project:
  - `uv run --python 3.14 scripts/inspect_session.py list --project KidStrongBedrock --limit 10`
- Summarize the newest session:
  - `uv run --python 3.14 scripts/inspect_session.py summary`
- Summarize the newest session using the ingestion profile:
  - `uv run --python 3.14 scripts/inspect_session.py --json --profile ingestion summary`
- Summarize a specific session by path or session id:
  - `uv run --python 3.14 scripts/inspect_session.py summary <path-or-session-id>`
- List sessions using the ingestion profile:
  - `uv run --python 3.14 scripts/inspect_session.py --json --profile ingestion list --limit 10`
- Print raw matching records:
  - `uv run --python 3.14 scripts/inspect_session.py records <path-or-session-id> --record-type assistant --tail 10`
- List subagents for a session:
  - `uv run --python 3.14 scripts/inspect_session.py subagents <path-or-session-id>`
- Summarize a specific subagent:
  - `uv run --python 3.14 scripts/inspect_session.py subagents <path-or-session-id> --agent-id <agent-id>`
- Summarize subagents using the ingestion profile:
  - `uv run --python 3.14 scripts/inspect_session.py --json --profile ingestion subagents <path-or-session-id>`

## Parsing Guidance

- The first `user` record with `parentUuid: null` is the session root; extract metadata from it.
- The `slug` field may not appear on early records; scan later records if needed.
- `custom-title` and `agent-name` records provide explicit session naming when present.
- Multiple `assistant` records may share the same `requestId` and `message.id`; treat them as one logical turn and keep the latest populated `usage`, `model`, and `stop_reason`.
- Tool errors are session-local: correlate `tool_use.id` with later `tool_result.tool_use_id` blocks before counting failures.
- Subagent files contain only `user`/`assistant` records. The first `user` record has `isSidechain: true` and an `agentId` field.
- Default `summary --json` is Claude-specific and now includes additive turn, hook, and tool-error fields. `records` remains the raw-record view.
- `list`, `summary`, and `subagents` prefer the SQLite cache when it exists and fall back to stateless parsing when it does not. `records` remains raw-log only.
- `refresh` incrementally imports changed sessions. `rebuild` removes the DB and backfills from raw logs.
- `locate` now reports DB path, row counts, last import time, pending-marker details, and hook configuration state.
- `--profile ingestion` emits the normalized `session_inspector_v2` contract for `list`, `summary`, and `subagents`. Keep the default profile when you want more Claude-specific operator detail.
- The shipped Claude hook config uses a `Stop` hook to keep the cache warm. The hook only fires on `end_turn` and `max_tokens` stops; `tool_use` stops are skipped to avoid running the full import on every tool call during agentic sessions.
- Hook failures write a pending marker and are reconciled on the next CLI run.
- The Stop hook imports the hook `transcript_path` immediately when Claude provides one, then writes a delayed reconcile marker because Stop can run before Claude appends final system records. Subsequent Stop hooks, normal `refresh`, and `refresh --pending` process due reconcile markers.
- If a Stop hook arrives without `transcript_path`, the hook only imports by `session_id` when that id resolves to an existing session JSONL. Unresolved hook session ids are recorded as non-retryable pending diagnostics instead of being retried indefinitely.
- The Stop hook runs before Claude Code writes `stop_hook_summary` and `turn_duration` system records to the JSONL. As a result, the hook-imported snapshot may underreport `hook_executions`, `completed_turn_count`, and `turn_durations_ms` for the final turn. A subsequent `refresh` captures these records once the session file is complete.
- The final assistant record in a session may have `stop_reason: null` even when the response is complete. This is a Claude Code streaming artifact — the last chunk is sometimes written without `stop_reason` populated. The parser preserves null rather than inferring `end_turn` to avoid misclassifying interrupted sessions.
- Tolerate additive fields — the schema evolves over time.
- `progress` records are interleaved in the UUID chain as first-class nodes.

## Analysis Tables

The SQLite cache now includes analysis-oriented tables and aggregate columns intended for fleet-scale queries without storing full prompt or thinking content.

Shared tables:

| Table | Purpose | Notes |
|------|---------|-------|
| `thinking_blocks` | Per-thinking-block metrics keyed by `turn_id` and `block_index` | Claude-only data in practice. Stores lengths, signature presence, and redaction flags, not the thinking text itself. |
| `user_messages` | Per-user-prompt metrics keyed by `session_id` and `message_index` | Excludes user records that are only `tool_result` blocks. Includes interrupt detection and prompt size metrics. |
| `server_tool_calls` | Per-server-tool invocation metrics keyed by `turn_id` and `tool_use_id` | Tracks `advisor`, `web_search`, `code_execution`, and future Anthropic-hosted server tools. Stores latency (from JSONL chunk timestamps), per-iteration token cost (from `usage.iterations[]`), model, and abort status. UNIQUE on `(session_id, tool_use_id)`. |

New aggregate/session columns:

| Table | Columns |
|------|---------|
| `sessions` | `total_thinking_blocks`, `total_redacted_blocks`, `total_thinking_content_len`, `total_reasoning_tokens`, `user_message_count`, `user_interrupt_count`, `total_user_char_count`, `server_tool_call_count`, `server_tool_aborted_count`, `server_tool_input_tokens`, `server_tool_output_tokens`, `server_tool_total_latency_ms`, `total_cache_create_5m`, `total_cache_create_1h` |
| `turns` | `text_block_count`, `thinking_block_count`, `tool_use_block_count`, `reasoning_output_tokens`, `speed`, `cache_create_5m`, `cache_create_1h` |
| `server_tool_calls` | `iteration_cache_create_5m`, `iteration_cache_create_1h` |
| `tool_calls` | `call_order` |

Claude-specific behavior:

- `thinking_blocks` is populated from `assistant.message.content[].type == "thinking"` blocks.
- `turns.reasoning_output_tokens` and `sessions.total_reasoning_tokens` remain `0` for Claude because reasoning depth is represented through `thinking_blocks`, not token snapshots.
- `user_messages.is_interrupt` is set when a real user prompt arrives before the active turn receives its `system.turn_duration` record.
- `server_tool_calls` is populated from `assistant.message.content[].type == "server_tool_use"` blocks paired with `*_tool_result` blocks via `tool_use_id`. Token attribution comes from `usage.iterations[]` entries whose `type` ends with `_message` (e.g., `advisor_message`), matched positionally. Aborted calls (no result block, no iterations) are stored with `is_aborted = 1` and null latency/tokens.
- Server-tool iteration tokens are **additive** to the parent turn's `usage.input_tokens` / `output_tokens`. The parent's totals are aggregated by Anthropic from the non-`*_message` iterations only (the regular `message`-type entries) — the `*_message` iteration tokens are billed separately and must be added on top when computing cost. `scripts/report_api_costs.py` reads `server_tool_calls.iteration_*` and rolls those tokens into per-model totals; the per-tool breakdown surfaces under `by_server_tool` in the report.
- Prompt-cache writes are split by TTL. Current logs record `usage.cache_creation.{ephemeral_5m_input_tokens, ephemeral_1h_input_tokens}` (and the same object on server-tool iterations). The importer reconciles the aggregate `cache_creation_input_tokens` with the labeled split into `cache_create_5m` / `cache_create_1h` columns such that `5m + 1h == max(aggregate, labeled_5m + labeled_1h)` (no labeled token is dropped; any unlabeled remainder defaults to 5m). `scripts/report_api_costs.py` prices 5-minute writes at `1.25x` base input and 1-hour writes at `2x`. Logs without the split (older sessions) price all cache writes at the 5-minute rate, matching prior behavior. In practice ~3/4 of cache-write tokens are 1-hour TTL, so this materially raises cache-write cost vs. the old all-`1.25x` assumption. This bumps the cache schema (`SCHEMA_VERSION`) and parser version: re-run `inspect_session.py refresh` (or `rebuild`) before `report_api_costs.py` to populate the new columns — opening a stale cache wipes it on the schema upgrade, so a report run before refresh shows `$0` until the cache is backfilled.
- `turns.speed` captures `assistant.message.usage.speed`, which marks Claude Code **fast mode** (research preview): `"standard"` for normal turns, `"fast"` for fast-mode Opus turns, `NULL` when the field is absent (older sessions / non-Opus turns). `scripts/report_api_costs.py` prices each turn per its speed — fast mode bills Opus at a higher rate (Opus 4.8 `$10/$50` MTok; Opus 4.7/4.6 `$30/$150` MTok) vs. the standard `$5/$25`. Fast mode is Opus-only; a `"fast"` value on Sonnet/Haiku (or any unrecognized speed) falls back to standard pricing and is surfaced via `scan.fast_speed_without_fast_price` / `scan.unknown_speed_turns`. Fast totals roll up under the report's `fast_mode` block. Note: the literal `"fast"` value is inferred from the field name and feature docs — no fast-mode session was available to confirm the exact string; a different value would price as `unknown_speed` (standard rates) and is a one-line fix in `FAST_SPEED_VALUE`, not a re-sync. Fast-mode cache rates are derived with the standard `0.1x` (read) / `1.25x` (5m write) / `2x` (1h write) ratios off the fast input rate (Anthropic does not publish fast-mode cache rates).

Example SQL:

Thinking redaction timeline by day:

```sql
SELECT
  DATE(t.timestamp) AS day,
  COUNT(*) AS thinking_blocks,
  SUM(tb.is_redacted) AS redacted_blocks,
  ROUND(100.0 * SUM(tb.is_redacted) / NULLIF(COUNT(*), 0), 1) AS redacted_pct
FROM thinking_blocks tb
JOIN turns t ON t.id = tb.turn_id
WHERE t.timestamp IS NOT NULL
GROUP BY day
ORDER BY day;
```

Read:Edit ratio by day:

```sql
SELECT
  DATE(t.timestamp) AS day,
  SUM(CASE WHEN tc.tool_name = 'Read' THEN 1 ELSE 0 END) AS reads,
  SUM(CASE WHEN tc.tool_name = 'Edit' THEN 1 ELSE 0 END) AS edits,
  ROUND(
    CAST(SUM(CASE WHEN tc.tool_name = 'Read' THEN 1 ELSE 0 END) AS REAL) /
    NULLIF(SUM(CASE WHEN tc.tool_name = 'Edit' THEN 1 ELSE 0 END), 0),
    2
  ) AS read_edit_ratio
FROM tool_calls tc
JOIN turns t ON t.id = tc.turn_id
WHERE t.timestamp IS NOT NULL
GROUP BY day
ORDER BY day;
```

Edit without a recent prior read of the same file:

```sql
SELECT
  e.session_id,
  e.tool_name,
  e.file_path,
  e.call_order
FROM tool_calls e
WHERE e.tool_name = 'Edit'
  AND e.file_path IS NOT NULL
  AND NOT EXISTS (
    SELECT 1
    FROM tool_calls r
    WHERE r.session_id = e.session_id
      AND r.call_order < e.call_order
      AND r.call_order > e.call_order - 20
      AND r.tool_name = 'Read'
      AND r.file_path = e.file_path
  )
ORDER BY e.session_id, e.call_order;
```

User interrupt rate by day:

```sql
SELECT
  DATE(timestamp) AS day,
  COUNT(*) AS prompts,
  SUM(is_interrupt) AS interrupts,
  ROUND(100.0 * SUM(is_interrupt) / NULLIF(COUNT(*), 0), 1) AS interrupt_pct
FROM user_messages
WHERE timestamp IS NOT NULL
GROUP BY day
ORDER BY day;
```

Advisor calls by day with total tokens and mean latency:

```sql
SELECT
  DATE(t.timestamp) AS day,
  COUNT(*) AS advisor_calls,
  SUM(stc.is_aborted) AS aborted,
  SUM(stc.iteration_input_tokens) AS total_input_tokens,
  SUM(stc.iteration_output_tokens) AS total_output_tokens,
  ROUND(AVG(CASE WHEN stc.latency_ms IS NOT NULL THEN stc.latency_ms END)) AS mean_latency_ms
FROM server_tool_calls stc
JOIN turns t ON t.id = stc.turn_id
WHERE stc.tool_name = 'advisor'
  AND t.timestamp IS NOT NULL
GROUP BY day
ORDER BY day;
```

## Resources

### scripts/

- `scripts/inspect_session.py`
  - Local Python 3.14 CLI for locating, listing, summarizing, filtering, and inspecting Claude Code session logs and subagent logs.
  - Use `uv run --python 3.14` to execute it.

### references/

- `references/recipes.md`
  - jq recipes for common extraction tasks
  - `uv` + Python 3.14 one-off snippets
  - Field-level guidance for session records
