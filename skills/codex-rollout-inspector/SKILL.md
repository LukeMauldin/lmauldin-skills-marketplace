---
name: codex-rollout-inspector
description: "Inspect local Codex CLI session logs under CODEX_HOME or ~/.codex: rollout JSONL, archived sessions, session_index, history, TUI logs, subagent rollouts, token/tool usage, PR links, metadata, date filters, and jq/Python analysis recipes."
---

# Codex Rollout Inspector

## Overview

Use this skill to inspect persisted Codex CLI session logs on the local machine.
Prefer rollout files for session analysis. Do not confuse them with composer history or optional TUI debug logs.
The inspector now keeps a derived SQLite cache at `${CODEX_HOME:-~/.codex}/inspector/session_inspector.db`. Raw rollout JSONL remains the source of truth.

Compared with Claude session logs, Codex rollout files support many of the same operator workflows, but not with identical fields:
- Token usage is available from cumulative `token_count` snapshots, not per-request `requestId` records.
- Tool usage is available from `response_item` tool call records, including native Codex call variants such as `local_shell_call`, `tool_search_call`, `web_search_call`, and `image_generation_call`.
- Function/custom tool outputs and tool-search outputs can be correlated by `call_id` to surface explicit tool failures.
- Subagent inspection is available from `session_meta.source.subagent.thread_spawn`, `forked_from_id`, and related child rollout files.
- Session naming comes from `session_index.jsonl` (`thread_name`) plus subagent metadata, not Claude-style `slug` or `custom-title` records.
- Turn durations come from `task_started` and `task_complete` event timestamps, not `system.turn_duration` records.
- PR links are extractable from assistant text and tool outputs when explicit GitHub PR URLs are present, but there is no dedicated `pr-link` record type.
- Cold rollouts may be stored as `.jsonl.zst`; the bundled inspector reads plain and zstd-compressed files transparently.

## Log Kinds

- Session rollouts:
  - Active: `$CODEX_HOME/sessions/YYYY/MM/DD/rollout-YYYY-MM-DDThh-mm-ss-<thread_id>.jsonl[.zst]`
  - Archived: `$CODEX_HOME/archived_sessions/rollout-YYYY-MM-DDThh-mm-ss-<thread_id>.jsonl[.zst]`
  - These are the replayable session logs and the primary target for analysis.
  - Codex 0.144.1 may compress cold rollouts after seven days. If both representations temporarily exist, prefer the plain `.jsonl` file.
- Session name index:
  - `$CODEX_HOME/session_index.jsonl`
  - Append-only thread-id to thread-name mapping.
- Composer/message history:
  - `$CODEX_HOME/history.jsonl`
  - Global input history, not full session replay.
- Optional TUI debug log:
  - `$CODEX_HOME/log/session-*.jsonl`
  - Only present when `CODEX_TUI_RECORD_SESSION=1`.

## Compatibility Policy

- Codex rollout files do not embed a dedicated schema version. Treat `session_meta.payload.cli_version` as the best available writer-version hint, and treat the upstream `RolloutLine` source/schema in `openai/codex` as the format authority.
- Minimum supported writer version: `codex-cli 0.144.1`. Older Codex versions are out of scope.
- This skill is tested against live `.jsonl` rollouts written by `codex-cli 0.144.1` and synthetic `.jsonl.zst` rollouts.
- This skill was audited against the exact upstream `rust-v0.144.1` tag released `2026-07-09`.
- Codex 0.144.1 adds persisted `world_state` and `inter_agent_communication_metadata` rollout items, richer compaction/window metadata, `thread_settings_applied` and related lifecycle events, and cold-rollout zstd compression. Unknown additive records remain visible in record/event counts even when they do not feed a derived metric.
- GPT-5.6 API responses report `cache_write_tokens`, but Codex 0.144.1 discards that field while converting response usage into persisted `token_count` records. The inspector cannot recover exact historical cache writes from 0.144.1 rollouts.

## Workflow

1. Locate the Codex state root and the relevant rollout file.
2. Confirm whether the user wants active sessions, archived sessions, or both.
3. Treat rollout files as newline-delimited `RolloutLine` JSON objects with top-level `timestamp`, `type`, and `payload`, optionally wrapped in zstd compression.
4. Start with a summary:
   - session metadata and git context
   - session name from `session_index.jsonl`
   - first user message preview, preferring the first `event_msg.user_message` and only falling back to user-role response items when needed
   - for subagents, treat that preview as the delegated task when the child rollout repeats the parent prompt history before the actual assignment
   - latest turn context, with `cwd` taken from the most recent `turn_context` when present
   - cumulative token usage snapshot and approximate API-call count
   - cache reads and cache writes when persisted; keep missing cache writes distinct from zero
   - tool usage frequency across function/custom/native Codex calls, plus explicit tool error counts derived from correlated outputs and failure-like native statuses
   - turn durations
   - PR links
   - child subagent rollouts, when present
5. Use targeted extraction:
   - `jq` for quick shell inspection
   - `scripts/inspect_rollout.py` for repeatable local parsing
   - `refresh` / `rebuild` when you need to backfill or repair the SQLite cache
   - `--profile ingestion` when downstream systems want the normalized `session_inspector_v2` contract
   - `uv run --python 3.14 python3 - <<'PY'` for ad hoc Python snippets

## Quick Start

- Locate roots and latest files with:
  - `uv run --python 3.14 scripts/inspect_rollout.py locate`
- Build or update the SQLite cache with:
  - `uv run --python 3.14 scripts/inspect_rollout.py refresh`
- Reconcile delayed/pending Stop-hook imports without scanning all rollouts with:
  - `uv run --python 3.14 scripts/inspect_rollout.py refresh --pending`
- Rebuild the cache from raw rollouts with:
  - `uv run --python 3.14 scripts/inspect_rollout.py rebuild`
- List recent rollout files with:
  - `uv run --python 3.14 scripts/inspect_rollout.py list --since 2026-07-09 --limit 20`
- List recent rollout files for one project/cwd with:
  - `uv run --python 3.14 scripts/inspect_rollout.py list --since 2026-07-09 --project KidStrongBedrock --limit 20`
- Summarize the newest rollout with:
  - `uv run --python 3.14 scripts/inspect_rollout.py summary`
- Summarize the newest rollout using the ingestion profile with:
  - `uv run --python 3.14 scripts/inspect_rollout.py --json --profile ingestion summary`
- List rollout files using the ingestion profile with:
  - `uv run --python 3.14 scripts/inspect_rollout.py --json --profile ingestion list --project KidStrongBedrock --limit 10`
- Summarize a specific rollout by path or thread id with:
  - `uv run --python 3.14 scripts/inspect_rollout.py summary <path-or-thread-id>`
- Print raw matching records with:
  - `uv run --python 3.14 scripts/inspect_rollout.py records <path-or-thread-id> --record-type response_item --tool-name exec_command --tail 20`
- List subagent rollouts for a parent thread with:
  - `uv run --python 3.14 scripts/inspect_rollout.py subagents <path-or-thread-id>`
- Summarize subagent rollouts using the ingestion profile with:
  - `uv run --python 3.14 scripts/inspect_rollout.py --json --profile ingestion subagents <path-or-thread-id>`
- Estimate what a date range of Codex usage would have cost at documented OpenAI API prices with:
  - `uv run --python 3.14 scripts/report_api_costs.py --begin 2026-07-09 --end 2026-07-10`
  - GPT-5.6 results are exact when `cache_write_tokens` exists. For 0.144.1 rollouts, the report emits lower/upper bounds because the writer omitted cache-write usage.

## Parsing Guidance

- Expect the first valid record to be `session_meta`.
- Treat `session_meta.payload.id` as the canonical thread id.
- Prefer `session_meta.payload.cli_version` as the rollout writer-version hint. There is no embedded `schema_version` or `format_version` field in `RolloutLine`.
- Support both plain `.jsonl` and compressed `.jsonl.zst` rollouts. Use the bundled script for transparent discovery and reading; raw `jq` requires decompression first.
- Use `session_index.jsonl` to recover the user-facing thread name.
- Prefer `event_msg.user_message` over user-role `response_item` messages when you need the true first user prompt. Response-item user messages can include injected environment/context blocks.
- For subagent rollouts, Codex may copy the parent prompt history into the child transcript before the delegated task. When a parent rollout is available, prefer the first child user message after the shared parent-prefix prompts as the delegated task preview.
- Prefer the last `turn_context.payload.cwd` over `session_meta.payload.cwd` when you need the most recent working directory.
- Treat `session_meta.agent_nickname`, `agent_role`, `agent_path`, `forked_from_id`, and `session_meta.source.subagent.thread_spawn` as the Codex equivalents of Claude subagent naming/identity fields.
- Codex does not have `slug`, `custom-title`, or `pr-link` records. Use `thread_name`, explicit subagent metadata, and URL extraction from message/tool-output text instead.
- Codex does not expose a Claude-style `requestId`. Token accounting should use the latest cumulative `token_count.info.total_token_usage` snapshot and, if needed, an approximate API-call count derived from changed snapshots, including `cache_write_tokens` in the snapshot signature when present.
- `cached_input_tokens` means cache reads. `cache_write_tokens` means cache writes and must remain nullable: `0` is an observed zero, while `NULL` means the rollout writer did not persist the field.
- OpenAI standard GPT-5.6 pricing bills cache writes at 1.25 times uncached input. `report_api_costs.py` prices Sol, Terra, Luna, and the `gpt-5.6` alias; it applies the documented long-context multiplier above 272K input tokens.
- Turn duration is derived from the wall-clock difference between `task_started` and `task_complete` events sharing the same `turn_id`.
- `list`, `summary`, and `subagents` prefer the SQLite cache when it exists and fall back to stateless parsing when it does not. `records` remains raw-rollout only.
- `refresh` incrementally imports changed rollouts. Child-thread targets are normalized to the root session tree so parent/subagent relationships stay consistent in SQLite. `rebuild` removes the DB and backfills from raw rollouts.
- When `summary` or `subagents` is called without an explicit path or thread id, prefer the latest matching parent session. Pass a child thread id or rollout path explicitly if you want a subagent summary directly.
- `locate` now reports DB path, row counts, last import time, pending-marker details, candidate `hooks.json` and `config.toml` paths across user/repo config layers, whether the rollout-inspector Stop hook is already present, and a ready-to-paste Stop-hook command.
- `--profile ingestion` emits a normalized `session_inspector_v2` shape intended for downstream ingestion. Keep the default profile for operator-facing inspection because it preserves more raw Codex-specific detail.
- SQLite keeps both the operator-facing `first_user_message` and the raw/derived split: `raw_first_user_message` is the literal first prompt recovered from the rollout, while `delegated_task` is the child-specific task preview when applicable.
- SQLite schema v7 is rebuild-oriented. Opening an older cache replaces its derived tables; run `rebuild` to backfill all raw rollouts after upgrading.
- Hooks require the `hooks` feature flag in an active `config.toml`:
  - `[features]`
  - `hooks = true`
- `codex_hooks = true` is a legacy alias in current Codex builds, but prefer `hooks = true` for new configuration. `inspect_rollout.py locate` reports both `hooks_enabled` and `legacy_codex_hooks_enabled`.
- Codex does not discover `hooks.json` from the plugin root. Configure the Stop hook in `~/.codex/hooks.json` or another active Codex config folder, and use the command from `inspect_rollout.py locate`. That command prefers an installed skill at `CODEX_HOME/skills/codex-rollout-inspector/...` and falls back to the newest plugin-cache copy under `CODEX_HOME/plugins/cache`.
- Do not overwrite an existing `hooks.json` during installation. Merge the rollout-inspector Stop hook into an active config-layer file instead; Codex loads matching hooks from multiple config layers.
- The Stop hook imports the hook `transcript_path` immediately when Codex provides one, then writes a delayed reconcile marker because Stop can run before Codex appends final turn-completion records. Subsequent Stop hooks and `refresh --pending` process due reconcile markers.
- Exact-path Stop imports use a metadata-only rollout tree index. They read one `session_meta` record per rollout for parent/child discovery instead of building the full operator-facing summary index on every hook process.
- If a Stop hook arrives without `transcript_path`, the hook only imports by `session_id` when that id resolves to an existing rollout. Unresolved hook session ids are recorded as non-retryable pending diagnostics instead of being treated as successful rollout targets.
- Pending reconciliation falls back from a missing rollout path to `session_id`, allowing markers to follow rollouts moved from `sessions/` to `archived_sessions/`.
- `--tool-name` can match native call types as well as named function/custom tools. For example, `--tool-name local_shell_call` isolates shell-call records even though they do not carry `payload.name`.
- Support both persistence levels:
  - Limited: core user-visible lifecycle and content
  - Extended: additional completion/end-state events
- Tolerate additive fields and record types. In 0.144.1, `world_state`, inter-agent metadata, compaction window identifiers, and additional lifecycle events are additive to the core `session_meta`/`turn_context`/`event_msg`/`response_item` flow.

## Analysis Tables

The SQLite cache now includes analysis-oriented tables and aggregate columns intended for longitudinal queries without storing full prompt content in SQLite.

Codex-specific tables:

| Table | Purpose | Notes |
|------|---------|-------|
| `reasoning_items` | Per-reasoning-item metrics keyed by `turn_id` and `block_index` | Stores `response_item.type == "reasoning"` rows, including encrypted payload length and whether plaintext reasoning content was present. |
| `user_messages` | Per-user-prompt metrics keyed by `session_id` and `message_index` | Populated from `event_msg` records where `payload.type == "user_message"`. |

New aggregate/session columns:

| Table | Columns |
|------|---------|
| `sessions` | `total_reasoning_items`, `total_encrypted_reasoning_items`, `total_reasoning_content_len`, `total_reasoning_tokens`, `total_cache_write`, `user_message_count`, `user_interrupt_count`, `total_user_char_count` |
| `turns` | `reasoning_item_count`, `tool_use_block_count`, `reasoning_output_tokens`, nullable `cache_write_tokens` |
| `token_usage_events` | nullable `cache_write_tokens`, nullable `cumulative_cache_write_tokens` |
| `tool_calls` | `call_order` |

Codex-specific behavior:

- The Codex SQLite schema is intentionally source-specific and rebuild-oriented. It does not keep Claude-only compatibility columns that were always `NULL` or `0`.
- Schema changes assume `rebuild` is acceptable. Do not rely on additive migrations for historical Codex DB files.
- `reasoning_items` stores Codex `response_item.type == "reasoning"` rows.
- `reasoning_items` columns are:
  - `block_type` for the rollout item type, currently `reasoning`
  - `is_redacted` for plaintext absence
  - `content_length` for plaintext length when available, otherwise encrypted payload length
  - `encrypted_content_length` for the raw encrypted payload size
  - `summary_item_count` for `payload.summary` list length
  - `has_plaintext_content` for explicit plaintext-vs-encrypted distinction
- `content_length` is the best available reasoning payload-length proxy: plaintext content length when present, otherwise encrypted payload length.
- `encrypted_content_length`, `summary_item_count`, and `has_plaintext_content` disambiguate the Codex-specific reasoning shape.
- `turns.reasoning_output_tokens` stores per-turn deltas derived from cumulative `token_count.info.total_token_usage.reasoning_output_tokens` snapshots when they can be computed.
- `sessions.total_reasoning_tokens` stores the latest cumulative `reasoning_output_tokens` value so reasoning spend is queryable without JSON extraction.
- `user_messages.is_interrupt` is set when a `user_message` arrives between `task_started` and `task_complete` boundaries for an active turn.
- Operator-facing JSON summaries still expose rollout-derived fields such as approximate API-call counts and cached-input-token snapshots. The schema cleanup only removed dead SQLite columns, not useful summary output.
- The `session_inspector_v2` ingestion profile now maps cache writes to `usage.tokens.cache_create`; it remains `null` for 0.144.1 rollouts because the writer omitted the source field.

Example SQL:

Reasoning-item sanity check:

```sql
SELECT
  COUNT(*) AS reasoning_items,
  SUM(is_redacted) AS redacted_items,
  SUM(content_length) AS payload_length
FROM reasoning_items;
```

Plaintext vs encrypted reasoning mix:

```sql
SELECT
  COUNT(*) AS reasoning_items,
  SUM(has_plaintext_content) AS plaintext_items,
  SUM(CASE WHEN has_plaintext_content = 0 THEN 1 ELSE 0 END) AS encrypted_only_items,
  SUM(summary_item_count) AS summary_fragments
FROM reasoning_items;
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

Reasoning-token usage by day:

```sql
SELECT
  DATE(timestamp) AS day,
  SUM(reasoning_output_tokens) AS reasoning_tokens
FROM turns
WHERE timestamp IS NOT NULL
GROUP BY day
ORDER BY day;
```

## Resources

### scripts/

- `scripts/inspect_rollout.py`
  - Local Python 3.14 CLI for locating, listing, summarizing, filtering, and traversing rollout files and subagent rollouts.
  - Use `uv run --python 3.14` to execute it.

### references/

- `references/recipes.md`
  - jq recipes
  - `uv` + Python 3.14 extraction snippets
  - field-level guidance for rollout records
  - token/tool/subagent/turn-duration/PR-link extraction patterns
