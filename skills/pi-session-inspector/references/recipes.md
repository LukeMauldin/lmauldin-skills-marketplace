# Pi Session Recipes

Extraction recipes for pi-coding-agent session logs. Raw JSONL is the source of truth;
`recorder.db` is an optional **read-only** accelerator. All `sqlite3` recipes open the DB
read-only (`?mode=ro`) — never write to the user's live database.

## Resolve pi state locations

```sh
PI_HOME="${PI_CODING_AGENT_DIR:-$HOME/.pi/agent}"
SESSIONS="$PI_HOME/sessions"
DB="$PI_HOME/recorder.db"
ls -d "$SESSIONS"/*/ 2>/dev/null            # one dir per project (slugified cwd)
[ -e "$DB" ] && echo "recorder.db present" || echo "recorder.db absent (JSONL-only)"
```

## Find the latest session file

```sh
ls -t "$SESSIONS"/*/*.jsonl | head -1
```

Latest for one project (slug substring):

```sh
ls -t "$SESSIONS"/*KidStrongBedrock*/*.jsonl | head -1
```

## Script wrapper

```sh
S="uv run --python 3.14 scripts/inspect_session.py"
$S locate
$S list --since 2026-06-01 --project KidStrongBedrock --limit 10
$S summary <session-id-or-path>
$S --profile ingestion summary <session-id-or-path>
$S records <session-id-or-path> --record-type message --role toolResult --tool-name bash --tail 10
$S subagents <session-id-or-path>
```

## jq Recipes

Set `F` to a session file first: `F=$(ls -t "$SESSIONS"/*/*.jsonl | head -1)`.

### Top-level record types

```sh
jq -r '.type' "$F" | sort | uniq -c | sort -rn
```

### Session metadata (root record)

```sh
jq -c 'select(.type=="session") | {version, id, cwd, timestamp}' "$F"
```

### Initial model and thinking level

```sh
jq -c 'select(.type=="model_change") | {provider, modelId, timestamp}' "$F" | head -1
jq -c 'select(.type=="thinking_level_change") | {thinkingLevel, timestamp}' "$F" | head -1
```

### First user message

```sh
jq -r 'select(.type=="message" and .message.role=="user")
       | (.message.content // [])[] | select(.type=="text") | .text' "$F" | head -1
```

### Message role histogram

```sh
jq -r 'select(.type=="message") | .message.role' "$F" | sort | uniq -c
```

### Assistant content block types

```sh
jq -r 'select(.type=="message" and .message.role=="assistant")
       | .message.content[]?.type' "$F" | sort | uniq -c
```

### Token usage and cost (summed per assistant message)

Each assistant message is one API response; usage is summable. Cost is pi-computed
(`0` for local providers).

```sh
jq -s '[ .[] | select(.type=="message" and .message.role=="assistant") | .message.usage ]
       | { responses: length,
           input:  (map(.input)        | add),
           output: (map(.output)       | add),
           cacheRead:  (map(.cacheRead)  | add),
           cacheWrite: (map(.cacheWrite) | add),
           total:  (map(.totalTokens)   | add),
           cost:   (map(.cost.total)    | add) }' "$F"
```

### Token/cost broken down by model

```sh
jq -r 'select(.type=="message" and .message.role=="assistant")
       | [.message.model, (.message.usage.input//0), (.message.usage.output//0)] | @tsv' "$F" \
 | awk -F'\t' '{i[$1]+=$2; o[$1]+=$3; c[$1]++} END{for(m in i) printf "%-28s resp=%d in=%d out=%d\n", m, c[m], i[m], o[m]}'
```

### Stop-reason distribution (real values: stop / toolUse / aborted / length / error)

```sh
jq -r 'select(.type=="message" and .message.role=="assistant") | .message.stopReason' "$F" \
 | sort | uniq -c
```

### Tool usage frequency

```sh
jq -r 'select(.type=="message" and .message.role=="assistant")
       | .message.content[]? | select(.type=="toolCall") | .name' "$F" | sort | uniq -c | sort -rn
```

### Tool failures (first-class via toolResult.isError)

```sh
jq -r 'select(.type=="message" and .message.role=="toolResult" and .message.isError==true)
       | .message.toolName' "$F" | sort | uniq -c
```

### Compaction events (context-window compaction)

```sh
jq -c 'select(.type=="compaction") | {timestamp, tokensBefore, firstKeptEntryId, fromHook}' "$F"
```

### Context injections

```sh
jq -r 'select(.type=="custom_message") | .customType' "$F" | sort | uniq -c
jq -r 'select(.type=="custom") | .customType' "$F" | sort | uniq -c
```

### Subagent invocations (parent JSONL — the sole clean source)

```sh
jq -c 'select(.type=="message" and .message.role=="toolResult" and .message.toolName=="subagent")
       | {mode: .message.details.mode,
          results: (.message.details.results | map({agent, model, stopReason,
                      input: .usage.input, output: .usage.output,
                      cost: .usage.cost, turns: .usage.turns,
                      task: (.task[0:60])}))}' "$F"
```

### GitHub PR links from text

```sh
jq -r 'select(.type=="message") | .message.content[]? | select(.type=="text") | .text' "$F" \
 | grep -oE 'https?://github\.com/[A-Za-z0-9._-]+/[A-Za-z0-9._-]+/pull/[0-9]+' | sort -u
```

## SQLite Recipes (read-only)

```sh
DB="$HOME/.pi/agent/recorder.db"
RO="file:$DB?mode=ro"
sqlite3 "$RO" ".tables"
sqlite3 "$RO" "SELECT * FROM v_session_summary LIMIT 10;"
```

### Daily cost / tokens

```sh
sqlite3 "$RO" "SELECT date(started_at/1000,'unixepoch','localtime') AS day,
  count(*) sessions, sum(total_input_tokens) input, sum(total_output_tokens) output,
  round(sum(total_cost),4) cost FROM sessions GROUP BY day ORDER BY day DESC;"
```

### Tool stats (call count, error rate, durations)

```sh
sqlite3 "$RO" "SELECT * FROM v_tool_stats;"
```

### Precise turn/iteration durations for one session (recorder.db-only)

```sh
sqlite3 "$RO" "SELECT turn_index, iteration_number, duration_ms, model_id, stop_reason
  FROM turns WHERE session_id='<uuid>' ORDER BY turn_index, iteration_number;"
```

### Subagent subprocess rows (NULL session_file — corroboration only)

```sh
sqlite3 "$RO" "SELECT id, datetime(started_at/1000,'unixepoch','localtime') started,
  model_id, total_input_tokens, total_output_tokens
  FROM sessions WHERE session_file IS NULL ORDER BY started_at;"
```

### Join recorder.db to its JSONL

`sessions.session_file` is the absolute path to the session JSONL; `sessions.id` matches
the JSONL `session.id` and the filename UUID.

```sh
sqlite3 "$RO" "SELECT id, session_file FROM sessions ORDER BY started_at DESC LIMIT 5;"
```

## Python 3.14 One-Off Recipes With `uv`

### Count record types

```sh
uv run --python 3.14 python3 - "$F" <<'PY'
import json, sys
from collections import Counter
c = Counter()
for line in open(sys.argv[1], encoding="utf-8"):
    line = line.strip()
    if line:
        try: c[json.loads(line).get("type")] += 1
        except json.JSONDecodeError: pass
for k, v in c.most_common(): print(f"{v:6d}  {k}")
PY
```

### Aggregate token usage and cost

```sh
uv run --python 3.14 python3 - "$F" <<'PY'
import json, sys
tot = {"responses":0,"input":0,"output":0,"cacheRead":0,"cacheWrite":0,"total":0,"cost":0.0}
for line in open(sys.argv[1], encoding="utf-8"):
    line = line.strip()
    if not line: continue
    try: rec = json.loads(line)
    except json.JSONDecodeError: continue
    m = rec.get("message")
    if rec.get("type") != "message" or not isinstance(m, dict) or m.get("role") != "assistant":
        continue
    u = m.get("usage") or {}
    tot["responses"] += 1
    for k in ("input","output","cacheRead","cacheWrite"): tot[k] += u.get(k) or 0
    tot["total"] += u.get("totalTokens") or 0
    tot["cost"]  += (u.get("cost") or {}).get("total") or 0.0
print(tot)
PY
```

### Extract subagent breakdown

```sh
uv run --python 3.14 python3 - "$F" <<'PY'
import json, sys
for line in open(sys.argv[1], encoding="utf-8"):
    line = line.strip()
    if not line: continue
    try: rec = json.loads(line)
    except json.JSONDecodeError: continue
    m = rec.get("message")
    if not (isinstance(m, dict) and m.get("role") == "toolResult" and m.get("toolName") == "subagent"):
        continue
    d = m.get("details") or {}
    for r in d.get("results", []):
        u = r.get("usage") or {}
        print(f"[{d.get('mode')}] {r.get('agent')} ({r.get('model')}) stop={r.get('stopReason')} "
              f"in={u.get('input')} out={u.get('output')} turns={u.get('turns')} task={(r.get('task') or '')[:60]!r}")
PY
```
