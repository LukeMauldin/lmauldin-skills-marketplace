# Claude Code Session Log Recipes

## Locate Claude Home

```bash
CLAUDE_ROOT="${CLAUDE_HOME:-$HOME/.claude}"
printf '%s\n' "$CLAUDE_ROOT"
```

## List Project Directories

```bash
CLAUDE_ROOT="${CLAUDE_HOME:-$HOME/.claude}"
ls -1 "$CLAUDE_ROOT/projects/"
```

## Find Session Files For A Project

```bash
CLAUDE_ROOT="${CLAUDE_HOME:-$HOME/.claude}"
PROJECT="KidStrongBedrock"  # substring match
find "$CLAUDE_ROOT/projects" -maxdepth 2 -name '*.jsonl' -path "*${PROJECT}*" | sort
```

## Find The Latest Session File (All Projects)

```bash
CLAUDE_ROOT="${CLAUDE_HOME:-$HOME/.claude}"
find "$CLAUDE_ROOT/projects" -maxdepth 2 -name '*.jsonl' -type f \
  | xargs ls -t 2>/dev/null | head -1
```

## Find Sessions Since A Date

Session files use UUIDs, not dates in filenames. Filter by the timestamp inside the first user record:

```bash
CLAUDE_ROOT="${CLAUDE_HOME:-$HOME/.claude}"
SINCE="2026-03-15"
find "$CLAUDE_ROOT/projects" -maxdepth 2 -name '*.jsonl' -type f | while read -r f; do
  ts=$(jq -r 'select(.type=="user" and .parentUuid==null) | .timestamp // empty' "$f" 2>/dev/null | head -1)
  if [ -n "$ts" ] && [ "$ts" \> "$SINCE" ]; then
    printf '%s\t%s\n' "$ts" "$f"
  fi
done | sort -k1
```

For efficient date-based listing, prefer the Python script:

```bash
uv run --python 3.14 scripts/inspect_session.py list --since 2026-03-15 --limit 20
```

## Ingestion Profile

Use the normalized ingestion-oriented contract when a downstream parser needs a stable summary shape:

```bash
uv run --python 3.14 scripts/inspect_session.py --json --profile ingestion summary
uv run --python 3.14 scripts/inspect_session.py --json --profile ingestion list --project KidStrongBedrock --limit 10
uv run --python 3.14 scripts/inspect_session.py --json --profile ingestion subagents
```

The ingestion schema version is `session_inspector_v2`.

## SQLite Cache Maintenance

Incremental refresh:

```bash
uv run --python 3.14 scripts/inspect_session.py refresh
uv run --python 3.14 scripts/inspect_session.py refresh --since 2026-03-15
uv run --python 3.14 scripts/inspect_session.py refresh 11111111-1111-1111-1111-111111111111
```

Full rebuild:

```bash
uv run --python 3.14 scripts/inspect_session.py rebuild
```

Inspect DB state and hook config:

```bash
uv run --python 3.14 scripts/inspect_session.py locate
```

## SQLite Query Recipes

Top sessions by tool errors:

```bash
sqlite3 "${CLAUDE_HOME:-$HOME/.claude}/inspector/session_inspector.db" \
  'select session_id, project, tool_error_count from sessions where is_subagent = 0 order by tool_error_count desc, start_timestamp desc limit 20;'
```

Recent imported sessions:

```bash
sqlite3 "${CLAUDE_HOME:-$HOME/.claude}/inspector/session_inspector.db" \
  'select session_id, start_timestamp, imported_at from sessions order by imported_at desc limit 20;'
```

PR links:

```bash
sqlite3 "${CLAUDE_HOME:-$HOME/.claude}/inspector/session_inspector.db" \
  'select session_id, repository, number, url from pr_links order by id desc limit 20;'
```

## Find Subagent Files For A Session

```bash
SESSION_DIR="$CLAUDE_ROOT/projects/<project>/<session-uuid>"
find "$SESSION_DIR/subagents" -name 'agent-*.jsonl' -type f 2>/dev/null | sort
```

## jq Recipes

Assume:

```bash
f=".../session-uuid.jsonl"
```

### Top-level record types

```bash
jq -r '.type' "$f" | sort | uniq -c | sort -rn
```

### Session metadata (from first user record)

```bash
jq -c 'select(.type=="user" and .parentUuid==null) | {sessionId, cwd, version, gitBranch, permissionMode, entrypoint, slug}' "$f" | head -1
```

### First user message

```bash
jq -r 'select(.type=="user" and .parentUuid==null) | .message.content' "$f" | head -1
```

### All user messages (excluding tool results)

```bash
jq -r 'select(.type=="user" and .parentUuid==null) | .message.content // empty' "$f"
```

### Session slug and titles

```bash
jq -r 'select(.slug != null) | .slug' "$f" | head -1
jq -r 'select(.type=="custom-title") | .customTitle' "$f"
jq -r 'select(.type=="agent-name") | .agentName' "$f"
```

### Models used

```bash
jq -r 'select(.type=="assistant") | .message.model // empty' "$f" | sort | uniq -c | sort -rn
```

### Tool usage frequency

```bash
jq -r 'select(.type=="assistant") | .message.content[]? | select(.type=="tool_use") | .name' "$f" \
  | sort | uniq -c | sort -rn
```

### Tool calls with inputs (specific tool)

```bash
TOOL="Bash"
jq -c "select(.type==\"assistant\") | .message.content[]? | select(.type==\"tool_use\" and .name==\"$TOOL\") | {name, input}" "$f"
```

### Token usage per API call (deduplicated by requestId)

```bash
jq -c '[.requestId, .message.usage] | select(.[0] != null)' "$f" \
  | sort -u -t',' -k1,1 \
  | jq -s 'map(.[1]) | {
      input_tokens: (map(.input_tokens) | add),
      output_tokens: (map(.output_tokens) | add),
      cache_creation: (map(.cache_creation_input_tokens) | add),
      cache_read: (map(.cache_read_input_tokens) | add),
      api_calls: length
    }'
```

Simpler (may double-count streamed chunks with same requestId):

```bash
jq -r 'select(.type=="assistant") | .message.usage | "\(.input_tokens // 0)\t\(.output_tokens // 0)"' "$f" \
  | awk -F'\t' '{i+=$1; o+=$2} END {printf "input: %d  output: %d  total: %d\n", i, o, i+o}'
```

### Turn durations

```bash
jq -r 'select(.type=="system" and .subtype=="turn_duration") | .durationMs' "$f"
```

Total turn duration:

```bash
jq -r 'select(.type=="system" and .subtype=="turn_duration") | .durationMs' "$f" \
  | awk '{s+=$1} END {printf "%d ms (%.1f min)\n", s, s/60000}'
```

### System record subtypes

```bash
jq -r 'select(.type=="system") | .subtype // "unknown"' "$f" | sort | uniq -c
```

### PR links

```bash
jq -c 'select(.type=="pr-link") | {prNumber, prUrl, prRepository}' "$f"
```

### Queue operations (background tasks)

```bash
jq -c 'select(.type=="queue-operation") | {operation, content, timestamp}' "$f"
```

### Assistant text responses only (no tool calls)

```bash
jq -r 'select(.type=="assistant") | .message.content[]? | select(.type=="text") | .text' "$f"
```

### Thinking blocks (chain-of-thought)

```bash
jq -r 'select(.type=="assistant") | .message.content[]? | select(.type=="thinking") | .thinking' "$f"
```

### Message chain (uuid → parentUuid linkage)

```bash
jq -c 'select(.uuid != null) | {type, uuid: .uuid[:8], parent: (.parentUuid // "null")[:8]}' "$f" | head -20
```

### Subagent overview from main session

```bash
jq -c 'select(.type=="user" and .isSidechain==true) | {agentId, content: (.message.content[:100] // "")}' "$f"
```

## Python 3.14 One-Off Recipes With uv

### Count record types

```bash
uv run --python 3.14 python3 - <<'PY'
import json
from collections import Counter
from pathlib import Path

path = Path(".../session-uuid.jsonl")
counter: Counter[str] = Counter()
for line in path.read_text(encoding="utf-8").splitlines():
    if not line.strip():
        continue
    obj = json.loads(line)
    counter[str(obj.get("type", "unknown"))] += 1

for key, value in counter.most_common():
    print(f"{value:6d} {key}")
PY
```

### Extract session metadata and first user message

```bash
uv run --python 3.14 python3 - <<'PY'
import json
from pathlib import Path

path = Path(".../session-uuid.jsonl")
session_meta = None
first_message = None

for raw in path.read_text(encoding="utf-8").splitlines():
    if not raw.strip():
        continue
    obj = json.loads(raw)
    if obj.get("type") == "user" and obj.get("parentUuid") is None:
        if session_meta is None:
            session_meta = {
                k: obj.get(k) for k in
                ("sessionId", "cwd", "version", "gitBranch", "permissionMode", "entrypoint")
            }
        if first_message is None:
            msg = obj.get("message", {})
            content = msg.get("content") if isinstance(msg, dict) else None
            if isinstance(content, str):
                first_message = content.strip()

print("session_meta:", json.dumps(session_meta, indent=2))
print("first_message:", first_message)
PY
```

### Aggregate token usage across a session

```bash
uv run --python 3.14 python3 - <<'PY'
import json
from pathlib import Path

path = Path(".../session-uuid.jsonl")
totals = {"input": 0, "output": 0, "cache_create": 0, "cache_read": 0}
seen_requests: set[str] = set()

for raw in path.read_text(encoding="utf-8").splitlines():
    if not raw.strip():
        continue
    obj = json.loads(raw)
    if obj.get("type") != "assistant":
        continue
    msg = obj.get("message", {})
    rid = obj.get("requestId")
    usage = msg.get("usage") if isinstance(msg, dict) else None
    if not isinstance(usage, dict) or not rid or rid in seen_requests:
        continue
    seen_requests.add(rid)
    totals["input"] += usage.get("input_tokens", 0)
    totals["output"] += usage.get("output_tokens", 0)
    totals["cache_create"] += usage.get("cache_creation_input_tokens", 0)
    totals["cache_read"] += usage.get("cache_read_input_tokens", 0)

totals["total"] = totals["input"] + totals["output"]
totals["api_calls"] = len(seen_requests)
print(json.dumps(totals, indent=2))
PY
```

### List all tool calls with timestamps

```bash
uv run --python 3.14 python3 - <<'PY'
import json
from pathlib import Path

path = Path(".../session-uuid.jsonl")
for raw in path.read_text(encoding="utf-8").splitlines():
    if not raw.strip():
        continue
    obj = json.loads(raw)
    if obj.get("type") != "assistant":
        continue
    ts = obj.get("timestamp", "")
    msg = obj.get("message", {})
    for block in msg.get("content", []) if isinstance(msg, dict) else []:
        if isinstance(block, dict) and block.get("type") == "tool_use":
            print(f"{ts}  {block.get('name', '?')}")
PY
```

## Script Wrapper

Use the bundled script for repeatable inspection:

```bash
uv run --python 3.14 scripts/inspect_session.py locate
uv run --python 3.14 scripts/inspect_session.py list --since 2026-03-15 --limit 10
uv run --python 3.14 scripts/inspect_session.py list --project KidStrongBedrock --limit 5
uv run --python 3.14 scripts/inspect_session.py summary
uv run --python 3.14 scripts/inspect_session.py --json --profile ingestion summary
uv run --python 3.14 scripts/inspect_session.py summary d9f8ce7f-76ac-4723-aa35-73e73cd6ced9
uv run --python 3.14 scripts/inspect_session.py records --record-type assistant --tool-name Bash --tail 10
uv run --python 3.14 scripts/inspect_session.py subagents
uv run --python 3.14 scripts/inspect_session.py --json --profile ingestion subagents
uv run --python 3.14 scripts/inspect_session.py subagents --agent-id a75ea2901a93491c7
```

## Summary Fields To Expect

`summary --json` now returns a stateless normalized session summary on top of the raw records. The highest-signal additive fields are:

- `turn_count`, `completed_turn_count`, `incomplete_turn_count`
- `turns[]` with per-turn model, stop reason, duration, token usage, and tool calls
- `tool_error_count`, `tool_errors_by_name`
- `hook_summary`
- `latest_git_branch`

Use `records` when you need the untouched raw JSONL records rather than the normalized summary.
