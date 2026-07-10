# Codex Rollout Recipes

## Resolve `CODEX_HOME`

```bash
CODEX_ROOT="${CODEX_HOME:-$HOME/.codex}"
printf '%s\n' "$CODEX_ROOT"
```

## Locate Relevant Files

```bash
CODEX_ROOT="${CODEX_HOME:-$HOME/.codex}"

find "$CODEX_ROOT" -maxdepth 2 \
  \( -name 'history.jsonl' \
  -o -name 'session_index.jsonl' \
  -o -name 'sessions' \
  -o -name 'archived_sessions' \
  -o -path '*/log' \) \
  -print | sort
```

## Find The Latest Rollout

Active:

```bash
CODEX_ROOT="${CODEX_HOME:-$HOME/.codex}"
find "$CODEX_ROOT/sessions" -maxdepth 4 -type f \
  \( -name 'rollout-*.jsonl' -o -name 'rollout-*.jsonl.zst' \) | sort | tail -n 1
```

Archived:

```bash
CODEX_ROOT="${CODEX_HOME:-$HOME/.codex}"
find "$CODEX_ROOT/archived_sessions" -maxdepth 1 -type f \
  \( -name 'rollout-*.jsonl' -o -name 'rollout-*.jsonl.zst' \) | sort | tail -n 1
```

## Version Scope

The inspector requires rollout files written by Codex 0.144.1 or newer. Check
`session_meta.payload.cli_version` before relying on derived data from an
unknown writer version.

For general date handling, prefer the Python script:

```bash
uv run --python 3.14 scripts/inspect_rollout.py list --since 2026-07-09 --limit 20
```

Estimate API-equivalent spend over a date range:

```bash
uv run --python 3.14 scripts/report_api_costs.py --begin 2026-07-09 --end 2026-07-10
uv run --python 3.14 scripts/report_api_costs.py --begin 2026-07-09T00:00:00Z --end 2026-07-10T23:59:59Z --json
```

GPT-5.6 cache writes are billed separately. Codex 0.144.1 does not persist the
API's `cache_write_tokens`, so affected results are emitted as lower/upper cost
bounds. An exact single cost is emitted when cache-write usage is present.

## Ingestion Profile

Use the normalized ingestion-oriented contract when a downstream parser needs a stable summary shape:

```bash
uv run --python 3.14 scripts/inspect_rollout.py --json --profile ingestion summary
uv run --python 3.14 scripts/inspect_rollout.py --json --profile ingestion list --project KidStrongBedrock --limit 10
uv run --python 3.14 scripts/inspect_rollout.py --json --profile ingestion subagents 019d2494-6c37-7c93-9df6-7ed84372b136
```

The ingestion schema version is `session_inspector_v2`.

For subagents, the operator-facing `first_user_message` may differ from `raw_first_user_message`. When the child rollout repeats the parent prompt history, the inspector derives `delegated_task` and uses that as the preview.

## SQLite Cache Maintenance

Incremental refresh:

```bash
uv run --python 3.14 scripts/inspect_rollout.py refresh
uv run --python 3.14 scripts/inspect_rollout.py refresh --since 2026-07-09
uv run --python 3.14 scripts/inspect_rollout.py refresh 019d2494-6c37-7c93-9df6-7ed84372b136
```

When you refresh a child thread id, the importer normalizes that target to the root parent session tree before updating SQLite.

Full rebuild:

```bash
uv run --python 3.14 scripts/inspect_rollout.py rebuild
```

Inspect DB state and hook config:

```bash
uv run --python 3.14 scripts/inspect_rollout.py locate
```

Enable Codex hooks in an active `config.toml` such as `~/.codex/config.toml` or `<repo>/.codex/config.toml`:

```toml
[features]
hooks = true
```

Install the rollout-inspector Stop hook by merging this fragment into an active `hooks.json` such as `~/.codex/hooks.json` or `<repo>/.codex/hooks.json`:

```json
{
  "hooks": {
    "Stop": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "script=\"$(python3 -c 'import os, sys; from pathlib import Path; codex_home = Path(os.environ.get(\"CODEX_HOME\", Path.home() / \".codex\")).expanduser(); installed = codex_home / \"skills\" / \"codex-rollout-inspector\" / \"scripts\" / \"sync_rollout.py\"; selected = installed if installed.is_file() else None; root = codex_home / \"plugins\" / \"cache\"; matches = sorted(root.glob(\"*/codex-rollout-inspector/*/skills/codex-rollout-inspector/scripts/sync_rollout.py\"), key=lambda p: (p.stat().st_mtime_ns, str(p)), reverse=True) if root.exists() else []; selected = selected or (matches[0] if matches else None); sys.stdout.write(str(selected) if selected else \"\")' 2>/dev/null)\"; [ -n \"$script\" ] && { \"$script\" || python3 \"$script\"; } || exit 0",
            "timeout": 30
          }
        ]
      }
    ]
  }
}
```

Do not replace unrelated hooks when you install this fragment. Codex loads matching `hooks.json` files from multiple active config layers, and `inspect_rollout.py locate` prints the same command plus candidate config paths in JSON form. The command prefers the installed skill at `${CODEX_HOME:-$HOME/.codex}/skills/codex-rollout-inspector/...` and falls back to the newest cached plugin copy if needed.

## SQLite Query Recipes

Recent active rollouts:

```bash
sqlite3 "${CODEX_HOME:-$HOME/.codex}/inspector/session_inspector.db" \
  'select session_id, project, start_timestamp from sessions where archived = 0 and is_subagent = 0 order by start_timestamp desc limit 20;'
```

Sessions with tool failures:

```bash
sqlite3 "${CODEX_HOME:-$HOME/.codex}/inspector/session_inspector.db" \
  'select session_id, tool_error_count, file_path from sessions where tool_error_count > 0 order by tool_error_count desc, start_timestamp desc limit 20;'
```

PR links:

```bash
sqlite3 "${CODEX_HOME:-$HOME/.codex}/inspector/session_inspector.db" \
  'select session_id, repository, number, url from pr_links order by id desc limit 20;'
```

## Resolve Session Names From `session_index.jsonl`

```bash
CODEX_ROOT="${CODEX_HOME:-$HOME/.codex}"
thread_id="019d4a0e-8152-7723-89ef-154d8306cea3"

jq -r "select(.id==\"$thread_id\") | .thread_name" "$CODEX_ROOT/session_index.jsonl" | tail -n 1
```

## Project-Scoped Navigation

Codex rollouts do not live under per-project directories. Filter by `cwd` instead:

```bash
uv run --python 3.14 scripts/inspect_rollout.py list --project KidStrongBedrock --limit 10
```

## jq Recipes

Assume:

```bash
f=".../rollout-...jsonl"
```

Codex 0.144.1 can compress cold rollouts to `.jsonl.zst`. The bundled Python
script reads both forms transparently. For a raw `jq` recipe, decompress first:

```bash
zstd -dc -- "$f" | jq -c 'select(.type == "session_meta") | .payload'
```

If `zstd` is unavailable, use Python 3.14's standard-library zstd support:

```bash
uv run --python 3.14 python3 -c \
  'import sys; from compression import zstd; sys.stdout.buffer.write(zstd.decompress(open(sys.argv[1], "rb").read()))' \
  "$f" | jq -c 'select(.type == "session_meta") | .payload'
```

### Top-level record types

```bash
jq -r '.type' "$f" | sort | uniq -c | sort -rn
```

### Session metadata plus git context

```bash
jq -c 'select(.type=="session_meta") | .payload' "$f" | head -n 1
```

### Latest turn context

```bash
jq -c 'select(.type=="turn_context") | .payload' "$f" | tail -n 1
```

### First user message preview

```bash
jq -r 'select(.type=="event_msg" and .payload.type=="user_message") | .payload.message' "$f" | head -n 1
```

### Response item types

```bash
jq -r 'select(.type=="response_item") | .payload.type // "unknown"' "$f" | sort | uniq -c | sort -rn
```

### Tool usage frequency

Function-backed tools:

```bash
jq -r '
  select(.type=="response_item" and .payload.type=="function_call")
  | .payload.name // "unknown"
' "$f" | sort | uniq -c | sort -rn
```

Custom tools:

```bash
jq -r '
  select(.type=="response_item" and .payload.type=="custom_tool_call")
  | .payload.name // "unknown"
' "$f" | sort | uniq -c | sort -rn
```

Native Codex call variants:

```bash
jq -r '
  select(.type=="response_item")
  | .payload.type // "unknown"
  | select(. == "local_shell_call" or . == "tool_search_call" or . == "web_search_call" or . == "image_generation_call")
' "$f" | sort | uniq -c | sort -rn
```

Combined function/custom/native tool accounting:

```bash
jq -r '
  select(.type=="response_item")
  | .payload as $p
  | if $p.type == "function_call" or $p.type == "custom_tool_call" then
      ($p.name // "unknown")
    elif $p.type == "local_shell_call" or $p.type == "tool_search_call" or $p.type == "web_search_call" or $p.type == "image_generation_call" then
      $p.type
    else
      empty
    end
' "$f" | sort | uniq -c | sort -rn
```

### Function and custom tool failures

Correlate call records to output records through `call_id` and keep only explicit failures where `output.success == false`:

```bash
jq -s '
  map(select(.type=="response_item" and (.payload.type=="function_call" or .payload.type=="custom_tool_call" or .payload.type=="function_call_output" or .payload.type=="custom_tool_call_output")))
  | reduce .[] as $item (
      {calls: {}, failures: []};
      if $item.payload.type == "function_call" or $item.payload.type == "custom_tool_call" then
        .calls[$item.payload.call_id] = ($item.payload.name // "unknown")
      elif (($item.payload.type == "function_call_output" or $item.payload.type == "custom_tool_call_output")
            and ($item.payload.output.success // null) == false) then
        .failures += [{
          call_id: $item.payload.call_id,
          name: (.calls[$item.payload.call_id] // $item.payload.name // "unknown"),
          content: ($item.payload.output.content // null)
        }]
      else
        .
      end
    )
  | .failures
' "$f"
```

### Latest cumulative token usage snapshot

```bash
jq -c '
  select(.type=="event_msg" and .payload.type=="token_count" and .payload.info != null)
  | .payload.info.total_token_usage
' "$f" | tail -n 1
```

### Approximate API-call count from changed cumulative token snapshots

Codex does not expose Claude-style `requestId`. This counts changes in the cumulative totals:

```bash
jq -r '
  select(.type=="event_msg" and .payload.type=="token_count" and .payload.info != null)
  | .payload.info.total_token_usage
  | [
      (.input_tokens // 0),
      (.cached_input_tokens // 0),
      (.cache_write_tokens // null),
      (.output_tokens // 0),
      (.reasoning_output_tokens // 0),
      (.total_tokens // 0)
    ]
  | @tsv
' "$f" | awk 'BEGIN{n=0} prev!=$0 {n++; prev=$0} END{print n}'
```

### Turn durations from `task_started` / `task_complete`

```bash
jq -s '
  map(select(.type=="event_msg" and (.payload.type=="task_started" or .payload.type=="task_complete")))
  | reduce .[] as $item (
      {started: {}, turns: []};
      if $item.payload.type == "task_started" then
        .started[$item.payload.turn_id] = $item.timestamp
      else
        .turns += [{
          turn_id: $item.payload.turn_id,
          started_at: .started[$item.payload.turn_id],
          completed_at: $item.timestamp
        }]
      end
    )
  | .turns
' "$f"
```

### Subagent rollouts from session metadata

Show subagent identity on the current rollout:

```bash
jq -c '
  select(.type=="session_meta")
  | .payload
  | {
      id,
      forked_from_id,
      source,
      agent_nickname,
      agent_role,
      agent_path
    }
' "$f" | head -n 1
```

Find child rollouts for one parent thread id:

```bash
parent="019d2494-6c37-7c93-9df6-7ed84372b136"
uv run --python 3.14 scripts/inspect_rollout.py --json subagents "$parent"
```

### PR links

Dedicated `pr-link` records do not exist. Extract explicit GitHub PR URLs from text-bearing records:

```bash
jq -r '
  select(.type=="event_msg" or .type=="response_item")
  | .payload
' "$f" \
  | rg -o 'https://github\.com/[^/[:space:]]+/[^/[:space:]]+/pull/[0-9]+' \
  | sort -u
```

## Python 3.14 One-Off Recipes With `uv`

### Count record types

```bash
uv run --python 3.14 python3 - <<'PY'
from __future__ import annotations
import json
from collections import Counter
from pathlib import Path

path = Path(".../rollout-...jsonl")
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

### Extract session name, session metadata, and latest turn context

```bash
uv run --python 3.14 python3 - <<'PY'
from __future__ import annotations
import json
from pathlib import Path

codex_root = Path.home() / ".codex"
path = Path(".../rollout-...jsonl")
thread_id = path.stem.split("-", 7)[-1]

thread_name = None
index_path = codex_root / "session_index.jsonl"
for raw in index_path.read_text(encoding="utf-8").splitlines():
    if not raw.strip():
        continue
    obj = json.loads(raw)
    if obj.get("id") == thread_id and isinstance(obj.get("thread_name"), str):
        thread_name = obj["thread_name"]

session_meta = None
latest_turn_context = None
for raw in path.read_text(encoding="utf-8").splitlines():
    if not raw.strip():
        continue
    obj = json.loads(raw)
    match obj.get("type"):
        case "session_meta":
            session_meta = obj["payload"]
        case "turn_context":
            latest_turn_context = obj["payload"]

print("thread_name:", thread_name)
print("session_meta:", json.dumps(session_meta, indent=2))
print("latest_turn_context:", json.dumps(latest_turn_context, indent=2))
PY
```

### Aggregate cumulative token usage and approximate API-call count

```bash
uv run --python 3.14 python3 - <<'PY'
from __future__ import annotations
import json
from pathlib import Path

path = Path(".../rollout-...jsonl")
latest_total = None
latest_last = None
previous_signature = None
api_call_count_approx = 0

for raw in path.read_text(encoding="utf-8").splitlines():
    if not raw.strip():
        continue
    obj = json.loads(raw)
    if obj.get("type") != "event_msg":
        continue
    payload = obj.get("payload", {})
    if payload.get("type") != "token_count":
        continue
    info = payload.get("info")
    if not isinstance(info, dict):
        continue
    total = info.get("total_token_usage")
    last = info.get("last_token_usage")
    if not isinstance(total, dict):
        continue
    signature = (
        total.get("input_tokens"),
        total.get("cached_input_tokens"),
        total.get("cache_write_tokens"),
        total.get("output_tokens"),
        total.get("reasoning_output_tokens"),
        total.get("total_tokens"),
    )
    if signature != previous_signature:
        api_call_count_approx += 1
        previous_signature = signature
    latest_total = total
    latest_last = last

print("api_call_count_approx:", api_call_count_approx)
print("latest_total:", json.dumps(latest_total, indent=2))
print("latest_last:", json.dumps(latest_last, indent=2))
PY
```

### Aggregate tool usage frequency

```bash
uv run --python 3.14 python3 - <<'PY'
from __future__ import annotations
import json
from collections import Counter
from pathlib import Path

path = Path(".../rollout-...jsonl")
tools: Counter[str] = Counter()

for raw in path.read_text(encoding="utf-8").splitlines():
    if not raw.strip():
        continue
    obj = json.loads(raw)
    if obj.get("type") != "response_item":
        continue
    payload = obj.get("payload", {})
    if payload.get("type") not in {"function_call", "custom_tool_call"}:
        continue
    tools[str(payload.get("name", "unknown"))] += 1

for name, count in tools.most_common():
    print(f"{count:6d} {name}")
PY
```

### Extract turn durations

```bash
uv run --python 3.14 python3 - <<'PY'
from __future__ import annotations
import json
from datetime import datetime
from pathlib import Path

path = Path(".../rollout-...jsonl")
starts: dict[str, datetime] = {}

def parse_ts(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))

for raw in path.read_text(encoding="utf-8").splitlines():
    if not raw.strip():
        continue
    obj = json.loads(raw)
    if obj.get("type") != "event_msg":
        continue
    payload = obj.get("payload", {})
    turn_id = payload.get("turn_id")
    if not isinstance(turn_id, str):
        continue
    event_type = payload.get("type")
    timestamp = parse_ts(obj["timestamp"])
    if event_type == "task_started":
        starts[turn_id] = timestamp
    elif event_type == "task_complete":
        started = starts.get(turn_id)
        if started is None:
            continue
        duration_ms = int((timestamp - started).total_seconds() * 1000)
        print(turn_id, duration_ms)
PY
```

### Extract explicit GitHub PR links

```bash
uv run --python 3.14 python3 - <<'PY'
from __future__ import annotations
import json
import re
from pathlib import Path

path = Path(".../rollout-...jsonl")
pattern = re.compile(r"https://github\\.com/[^/\\s]+/[^/\\s]+/pull/\\d+")
links: set[str] = set()

def walk_strings(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, list):
        for item in value:
            yield from walk_strings(item)
    elif isinstance(value, dict):
        for item in value.values():
            yield from walk_strings(item)

for raw in path.read_text(encoding="utf-8").splitlines():
    if not raw.strip():
        continue
    obj = json.loads(raw)
    payload = obj.get("payload")
    if not isinstance(payload, dict):
        continue
    for text in walk_strings(payload):
        links.update(pattern.findall(text))

for link in sorted(links):
    print(link)
PY
```

## Script Wrapper

Use the bundled script for repeatable inspection:

```bash
uv run --python 3.14 scripts/inspect_rollout.py locate
uv run --python 3.14 scripts/inspect_rollout.py list --since 2026-07-09 --limit 10
uv run --python 3.14 scripts/inspect_rollout.py list --project KidStrongBedrock --limit 10
uv run --python 3.14 scripts/inspect_rollout.py summary
uv run --python 3.14 scripts/inspect_rollout.py --json --profile ingestion summary
uv run --python 3.14 scripts/inspect_rollout.py summary 019d316a-4292-7b71-b420-be6dbd0855f2
uv run --python 3.14 scripts/inspect_rollout.py records --record-type response_item --tool-name exec_command --tail 10
uv run --python 3.14 scripts/inspect_rollout.py subagents 019d2494-6c37-7c93-9df6-7ed84372b136
```

When `summary` is called without an explicit path or thread id, it picks the latest matching parent session. Pass a child thread id or rollout path explicitly when you want a subagent session directly.
