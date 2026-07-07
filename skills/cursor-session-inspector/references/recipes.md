# Cursor Session Inspector Recipes

## List Recent UI Composers

```sh
sqlite3 "$HOME/Library/Application Support/Cursor/User/globalStorage/state.vscdb" \
  "SELECT json_extract(value, '$.composerId'), json_extract(value, '$.name'), json_extract(value, '$.lastUpdatedAt') FROM cursorDiskKV WHERE key LIKE 'composerData:%' ORDER BY json_extract(value, '$.lastUpdatedAt') DESC LIMIT 20;"
```

## Replay One UI Composer

```sh
uv run --python 3.14 scripts/inspect_session.py records <composer-id> --record-type bubble --tail 200
```

## Cross-Check Token Sources

```sh
uv run --python 3.14 scripts/inspect_session.py --json summary <composer-id> | jq '.execution.token_usage'
uv run --python 3.14 scripts/inspect_session.py records <composer-id> --record-type bubble --tail 200 | jq '[.[].payload.tokenCount] | add'
```

Stop-hook payloads include generation-level `input_tokens`, `output_tokens`, `cache_read_tokens`, and `cache_write_tokens`; summaries prefer those values when available. Per-bubble `tokenCount` can be zero on small turns, so the cache falls back to bubble totals and `composerData.usageData` only when no hook token event exists.

Global flags must be placed before the subcommand:

```sh
uv run --python 3.14 scripts/inspect_session.py --json summary <composer-id> | jq '.execution.token_usage'
uv run --python 3.14 scripts/inspect_session.py --json subagents <composer-id> | jq '.[] | {session_id, token_source, token_total, token_usage}'
```

If child composers show `token_source: "none"` while the parent shows `token_source: "hook"`, Cursor did not provide stop-hook token fields for those child sessions. Use `context.context_tokens_used`, turn counts, and transcript details as fallback observability, but do not treat those as billable token totals.

## Enable Raw Hook Payload Capture Temporarily

```json
{
  "version": 1,
  "hooks": {
    "stop": [
      {
        "matcher": "*",
        "command": "CURSOR_INSPECTOR_CAPTURE_HOOK_PAYLOAD=1 sh -c 'p=$(ls -dt ${HOME}/.cursor/plugins/cache/*/cursor-session-inspector/*/skills/cursor-session-inspector/scripts/sync_session.py 2>/dev/null | head -1); [ -n \"$p\" ] && uv run --python 3.14 \"$p\"'",
        "timeout": 30
      }
    ]
  }
}
```

Raw captures are troubleshooting artifacts under `~/.cursor/inspector/payload-captures/` and may include user or workspace metadata. Leave capture disabled for normal operation.

## Tool Frequency

```sh
uv run --python 3.14 scripts/inspect_session.py summary <composer-id> --json | jq '.execution.tool_usage'
uv run --python 3.14 scripts/inspect_session.py records <composer-id> --record-type tool_result --tail 200
```

## Subagent Fan-Out

```sh
uv run --python 3.14 scripts/inspect_session.py --json subagents <parent-composer-id>
uv run --python 3.14 scripts/inspect_session.py records <parent-composer-id> --record-type composer --json | jq '.[0].payload.subagentComposerIds'
```

## AI Percentage Of Recent Commits

```sh
uv run --python 3.14 scripts/report_ai_attribution.py --by commit --limit 20
uv run --python 3.14 scripts/report_ai_attribution.py --begin 2026-04-01 --end 2026-05-17 --by branch --limit 20
```

## CLI Blob Walk Pseudocode

```text
read ~/.cursor/chats/<workspace>/<agentId>/store.db
parse meta key 0 as hex-encoded JSON
start at latestRootBlobId
if blob starts with 0x0A 0x20, read repeated 32-byte child hashes
walk children depth-first with cycle detection
if blob starts with "{", parse as JSON message
otherwise keep it as raw text
```
