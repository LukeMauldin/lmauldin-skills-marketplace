# Task JSON Field Reference

Maps ClickUp UI labels to JSON paths. Applies to:
- `get_task.py` output → `task.<field>`
- `fetch_filtered_tasks.py` output → `tasks[].<field>` (array of tasks)

## Field Map

| UI Label | JSON Path | Type | Example Value |
|----------|-----------|------|---------------|
| **Status** | `task.status.status` | string | `"in progress"` |
| **Assignees** | `task.assignees` | array | `[{"id": 75349906, "username": "Luke Mauldin", "email": "..."}]` |
| **Priority** | `task.priority` | object/null | `{"priority": "high"}` or `null` |
| **Sprint points** | `task.points` | integer/null | `4` |
| **Tags** | `task.tags` | array | `[{"name": "backend", "tag_bg": "#FF7FAB"}]` |
| **Start Date** | `task.start_date` | string/null | `"1704124800000"` (ms epoch) |
| **Due Date** | `task.due_date` | string/null | `"1704211200000"` (ms epoch) |
| **Time estimate** | `task.time_estimate` | integer/null | milliseconds |
| **Time spent** | `task.time_spent` | integer | `0` (milliseconds) |
| **Created** | `task.date_created` | string | `"1704124800000"` (ms epoch) |
| **Updated** | `task.date_updated` | string | `"1704211200000"` (ms epoch) |

## Field Detail Examples

```jsonc
// Status - nested object
"status": {
  "id": "c90100118193_Avibb2NB",  // Internal status ID
  "status": "in progress",        // Display name (use this)
  "color": "#4466ff",
  "type": "custom"                // "open", "custom", "done", "closed"
}

// Assignees - array of user objects
"assignees": [
  {
    "id": 75349906,               // User ID (for API calls)
    "username": "Luke Mauldin",   // Display name
    "email": "luke.mauldin@kidstrong.com",
    "initials": "LM",
    "color": "#5d4037"
  }
]

// Priority - null when empty, object when set
"priority": null                  // Empty
"priority": {
  "id": "2",
  "priority": "high",             // "urgent", "high", "normal", "low"
  "color": "#ffcc00"
}

// Tags - array of tag objects
"tags": [
  {
    "name": "backend",            // Tag name (use this)
    "tag_fg": "#FF7FAB",
    "tag_bg": "#FF7FAB"
  }
]

// Points (Sprint points) - top-level integer
"points": 4                       // null when not set
```

## Accessing Fields with jq

```bash
# get_task.py (single task)
uv run --python 3.14 scripts/get_task.py 868abc | jq -r '.task.status.status'
uv run --python 3.14 scripts/get_task.py 868abc | jq -r '.task.assignees[].username'
uv run --python 3.14 scripts/get_task.py 868abc | jq -r '.task.points // "unset"'
uv run --python 3.14 scripts/get_task.py 868abc | jq -r '.task.tags[].name'
uv run --python 3.14 scripts/get_task.py 868abc | jq -r '.task.priority.priority // "none"'

# fetch_filtered_tasks.py (array of tasks)
uv run --python 3.14 scripts/fetch_filtered_tasks.py --preset server | jq -r '.tasks[].status.status'
uv run --python 3.14 scripts/fetch_filtered_tasks.py --preset server | jq '[.tasks[] | {name, points, status: .status.status}]'
```
