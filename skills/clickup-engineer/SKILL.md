---
name: clickup-engineer
description: |
  Interact with KidStrong ClickUp as a backend server engineer. Use when:
  (1) Creating/updating/closing ClickUp tasks — defaults to current sprint, Open status, assigned to current user
  (2) Grooming server team backlog — filtering, reviewing, bulk processing tickets
  (3) Reading or editing ClickUp documents and pages
  (4) Searching ClickUp workspace by keyword or custom fields (Apps, Quarter, Stage)
  (5) Working around MCP tool limitations with direct API scripts
  (6) Time tracking, tags, chat messages, or workspace hierarchy navigation
  (7) Generating ticket reports or documentation from ClickUp data
  (8) Bulk updating or closing multiple tasks
  (9) Parsing ClickUp URLs to extract task/document/page IDs
  Includes workspace IDs, custom field definitions, MCP workflow guidance, API patterns, and 18 CLI scripts specific to KidStrong.
---

# ClickUp Engineer Skill

Work with KidStrong ClickUp for backend server team task management.

## Quick Reference

| Resource | ID |
|----------|-----|
| Workspace | `12606327` |
| Tech Space | `16581563` |
| Tech Roadmap Folder | `90060144434` |
| Product Roadmap List | `900600273627` |
| Server Sprint Folder | `90100118193` |

**Server Sprint Statuses:** Open, in progress, in review, testing, blocked, pending live, completed, Closed

**Current Sprint List ID:** Resolve dynamically with `scripts/get_current_sprint.py`.

> **Note:** Task descriptions support markdown; comments do not (API limitation). See [references/text-formatting.md](references/text-formatting.md) for details.

## Requirements

- **Python:** 3.14+ (enforced by all scripts)
- **uv:** Required to run scripts with correct Python version
- **Dependencies:** None (stdlib only—no pip install required)
- **Authentication:** Direct ClickUp API scripts resolve the token in this order — (1) the `CLICKUP_API_TOKEN` environment variable (used first when set), then (2) the file `~/.agents/clickup_key.txt`, whose **entire contents are the token** (nothing else; trailing newline ignored). Provide either one. ClickUp MCP tools do not need the token. Shared resolver: `scripts/clickup_auth.py` (`resolve_token()`).

## Execution Mode Selection

Choose the implementation path based on what is actually available in the current client/session:

1. **Prefer ClickUp MCP tools first** for any operation they support, especially when `CLICKUP_API_TOKEN` is unavailable.
2. **Use bundled Python scripts** when MCP lacks the required capability, or when the script provides materially better behavior (for example: server-team defaults, dry-run support, pagination, or bulk operations) and `CLICKUP_API_TOKEN` is available.
3. **Do not attempt token-gated scripts without `CLICKUP_API_TOKEN`.** Fall back to MCP when there is an MCP equivalent.
4. **If the operation is script-only and `CLICKUP_API_TOKEN` is missing, stop and state the limitation clearly** instead of pretending the script path will work.

`generate_ticket_docs.py` is the main exception: it can run without `CLICKUP_API_TOKEN` unless `--fetch-comments` is used.

> **Full script parity:** With `CLICKUP_API_TOKEN` set, the 18 most-used MCP tools — task CRUD, comments, filtering, get_list, get_folder, **search, document reads, workspace hierarchy, tags, links, dependencies, delete, and member lookup** — all have script equivalents, so an agent with only `bash` + the token needs no ClickUp MCP for them. See [references/mcp-coverage-matrix.md](references/mcp-coverage-matrix.md). MCP remains required only for the ops under *MCP Required* below.

## Skill Contents

**All files below are bundled with this skill—no additional installation required.**

Claude accesses these files automatically when this skill is triggered. Paths are relative to this skill's directory (the folder containing `SKILL.md`). Do not assume the harness working directory; use absolute paths derived from the skill directory or run scripts with the skill directory as the working directory.

| Directory | Contents |
|-----------|----------|
| `scripts/` | Python CLI tools (bundled, executed by Claude) |
| `references/` | Configuration data (bundled, read on-demand) |

**Cross-script imports:** Some scripts import others (e.g., `create_task.py` imports `get_current_sprint`). Claude handles path resolution automatically when invoking scripts.

**References:**
- [Workspace Structure](references/workspace-structure.md) - Full hierarchy, IDs, URL parsing patterns, task ID formats, API endpoints
- [Custom Fields](references/custom-fields.md) - Field IDs and option values for Apps, Quarter, Stage, Year, etc.
- [Statuses](references/statuses.md) - Status IDs and workflow
- [MCP Workflows](references/mcp-workflows.md) - MCP tool parameters, workflows, and URL-to-ID parsing
- [Task JSON Fields](references/task-json-fields.md) - Maps ClickUp UI labels to JSON paths in script output
- [Text Formatting](references/text-formatting.md) - Markdown support in descriptions and comments
- [ClickUp API v2 OpenAPI Spec](references/clickup-api-v2.json) - Full API reference (80 endpoints). **Load only for advanced API debugging.**

## Available Scripts

Most scripts require `CLICKUP_API_TOKEN`. The exception is `generate_ticket_docs.py`, which only needs the token when `--fetch-comments` is used.

| Script | Token Requirement | Purpose |
|--------|-------------------|---------|
| `get_task.py` | Required | **Retrieve task details by ID (JSON for LLM consumption)** |
| `get_list.py` | Required | Retrieve list details by ID |
| `fetch_comments.py` | Required | Fetch comments only (lightweight, supports pagination) |
| `get_current_sprint.py` | Required | Resolve current sprint list ID for a folder by date |
| `create_task.py` | Required | Create new task with server team defaults |
| `fetch_filtered_tasks.py` | Required | Fetch tasks with custom field filtering |
| `generate_ticket_docs.py` | Only for `--fetch-comments` | Generate markdown docs for review |
| `update_task.py` | Required | Update single task (status, comment, assignee, etc.) |
| `bulk_update_tasks.py` | Required | Bulk close, update, or move multiple tasks |
| `get_folder.py` | Required | Retrieve folder details by ID (+ shared list helper) |
| `get_custom_fields.py` | Required | List a list's custom fields (field IDs + option UUIDs for writes) |
| `resolve_members.py` | Required | Resolve workspace members by name/email/ID (live `GET /team`) |
| `get_workspace_hierarchy.py` | Required | Compose the spaces > folders > lists tree |
| `docs.py` | Required | Read Docs (v3): `list-pages` / `get-pages` |
| `search.py` | Required | Keyword search across task names + doc titles (substring) |
| `task_relations.py` | Required | Add tag / link / dependency; remove dependency (mutations) |
| `delete_task.py` | Required | Delete task(s) — dry-run by default, `--yes` to execute (destructive) |
| `attach_file.py` | Required | Upload local file(s) to a task (native multipart, no base64 round-trip) |

> **MCP parity:** These scripts make the 18 most-used ClickUp MCP tools available with only `bash` + `CLICKUP_API_TOKEN` (no MCP). See [references/mcp-coverage-matrix.md](references/mcp-coverage-matrix.md) for the tool-by-tool mapping and verification.

### get_task.py

Retrieve detailed task information by ID. Outputs structured JSON by default, optimized for LLM consumption. **By default, includes `markdown_description` for rich text formatting.**

```bash
# Get task details as JSON (default, with markdown description)
uv run --python 3.14 scripts/get_task.py 868abc123

# Get human-readable summary
uv run --python 3.14 scripts/get_task.py 868abc123 --format summary

# Include comments in output
uv run --python 3.14 scripts/get_task.py 868abc123 --include-comments

# Disable markdown description (plain text only)
uv run --python 3.14 scripts/get_task.py 868abc123 --no-markdown

# Quiet mode (JSON only, no stderr messages)
uv run --python 3.14 scripts/get_task.py 868abc123 --quiet

# Multiple tasks at once
uv run --python 3.14 scripts/get_task.py 868abc1 868abc2 868abc3
```

**JSON Output Structure:**
```json
{
  "task": {
    "id": "868abc123",
    "name": "Task name",
    "markdown_description": "## Objective\n\nImplement...",
    "description": "Objective: Implement...",
    "status": { "status": "in progress" },
    "assignees": [...],
    "custom_fields": [...],
    ...
  },
  "comments": [...],
  "metadata": {
    "fetched_at": "2026-01-02T...",
    "task_id": "868abc123"
  }
}
```

For field-by-field JSON path mapping, see [references/task-json-fields.md](references/task-json-fields.md).

### get_list.py

Retrieve list details by ID.

```bash
# Get list details as JSON (default)
uv run --python 3.14 scripts/get_list.py 90100118193

# Get human-readable summary
uv run --python 3.14 scripts/get_list.py 90100118193 --format summary

# Quiet mode (JSON only, no stderr messages)
uv run --python 3.14 scripts/get_list.py 90100118193 --quiet

# Multiple lists
uv run --python 3.14 scripts/get_list.py 90100118193 900600273627
```

**JSON Output Structure:**
```json
{
  "list": {
    "id": "90100118193",
    "name": "Server Sprint 2026-01-06 to 2026-01-17",
    "folder": { "name": "Server Sprints" }
  },
  "metadata": {
    "fetched_at": "2026-01-02T...",
    "list_id": "90100118193"
  }
}
```

### fetch_comments.py

Lightweight script to fetch only comments for a task. Use when you already have task data and just need comments (avoids refetching full task).

```bash
# Get comments for a task
uv run --python 3.14 scripts/fetch_comments.py 868abc123

# Multiple tasks
uv run --python 3.14 scripts/fetch_comments.py 868abc1 868abc2 868abc3

# Multiple pages
uv run --python 3.14 scripts/fetch_comments.py 868abc123 --pages 3

# Quiet mode (JSON only)
uv run --python 3.14 scripts/fetch_comments.py 868abc123 --quiet
```

**JSON Output:**
```json
{
  "task_id": "868abc123",
  "comments": [...],
  "count": 5
}
```

### get_current_sprint.py

Resolve the current sprint list ID for a folder by matching the date range in list names.

This script requires `CLICKUP_API_TOKEN`. If the token is unavailable but ClickUp MCP tools are available, use the hierarchy workflow in [references/mcp-workflows.md](references/mcp-workflows.md) to locate the active sprint list manually.

```bash
# Current server sprint (today)
uv run --python 3.14 scripts/get_current_sprint.py --team server

# Specify date (ISO-8601)
uv run --python 3.14 scripts/get_current_sprint.py --team server --date 2026-01-02

# Output just the list ID
uv run --python 3.14 scripts/get_current_sprint.py --team server --format id

# Fallback to latest sprint if no date range matches
uv run --python 3.14 scripts/get_current_sprint.py --team server --fallback latest
```

### create_task.py

Create new tasks with server team defaults. Unless overridden:
- **List:** Current server sprint (resolved by date via `get_current_sprint.py`)
- **Status:** Open
- **Assignee:** Current user (determined from API token)
- **Description format:** Objective / Business Justification / Technical Details

```bash
# Basic creation (uses all defaults)
uv run --python 3.14 scripts/create_task.py "Implement user auth caching"

# With description sections
uv run --python 3.14 scripts/create_task.py "Implement user auth caching" \
  --objective "Add Redis caching for user authentication tokens" \
  --justification "Reduce database load and improve response times" \
  --details "Use Redis with 15-minute TTL. Update auth middleware."

# Override defaults
uv run --python 3.14 scripts/create_task.py "Fix login bug" --status "in progress" --assignee bob

# Add to Product Roadmap instead of sprint
uv run --python 3.14 scripts/create_task.py "New feature idea" --list roadmap

# Set custom fields
uv run --python 3.14 scripts/create_task.py "Server enhancement" --apps Server --quarter Q1

# Dry run (show what would be created)
uv run --python 3.14 scripts/create_task.py "Test task" --dry-run
```

**Description Template:**
```markdown
## Objective
(2-5 sentences describing what needs to be done)

## Business Justification
(2-3 sentences explaining why this matters)

## Technical Details
(as long as needed - implementation approach, files to modify, etc.)
```

### fetch_filtered_tasks.py

Fetch tasks filtered by custom fields (what MCP can't do).

```bash
# Server backlog (preset)
uv run --python 3.14 scripts/fetch_filtered_tasks.py --preset server -o server.json

# Coach backlog
uv run --python 3.14 scripts/fetch_filtered_tasks.py --preset coach -o coach.json

# Custom filter
uv run --python 3.14 scripts/fetch_filtered_tasks.py --list-id 900600273627 \
  --custom-field "FIELD_ID=OPTION_ID" -o tasks.json
```

### generate_ticket_docs.py

Convert task JSON to reviewable markdown documentation.

```bash
# Basic generation
uv run --python 3.14 scripts/generate_ticket_docs.py tasks.json -o ./tickets

# With legacy tech flagging and comments
uv run --python 3.14 scripts/generate_ticket_docs.py tasks.json -o ./tickets \
  --flag-legacy --fetch-comments --exclude-closed
```

Outputs:
- `INDEX.md` - Summary table with all tickets
- `{task_id}.md` - Individual ticket files with grooming checkboxes

### update_task.py

Update a single task (when MCP unavailable or need more control).

```bash
# Close a task with comment
uv run --python 3.14 scripts/update_task.py 868abc123 --status Closed \
  --comment "Closing as stale - no longer relevant"

# Update multiple fields
uv run --python 3.14 scripts/update_task.py 868abc123 --status "in progress" \
  --priority high --assignee me

# Add comment only
uv run --python 3.14 scripts/update_task.py 868abc123 --comment "Starting work on this"

# View current state (dry run)
uv run --python 3.14 scripts/update_task.py 868abc123 --dry-run
```

### bulk_update_tasks.py

Execute batch operations on multiple tasks.

```bash
# Close multiple tasks from file
uv run --python 3.14 scripts/bulk_update_tasks.py close --ids-file to_close.txt \
  --comment "Closing as part of backlog grooming"

# Update quarter on multiple tasks
uv run --python 3.14 scripts/bulk_update_tasks.py update --ids 868a 868b 868c --quarter Q1

# Move tasks to sprint
SPRINT_ID=$(uv run --python 3.14 scripts/get_current_sprint.py --team server --format id)
uv run --python 3.14 scripts/bulk_update_tasks.py move --ids-file sprint_tasks.txt \
  --list-id "$SPRINT_ID"

# Dry run
uv run --python 3.14 scripts/bulk_update_tasks.py close --ids 868abc --dry-run
```

### get_folder.py

Retrieve folder details (MCP `clickup_get_folder`). Exposes a `get_folder_lists()` helper that `get_current_sprint.py` reuses.

```bash
uv run --python 3.14 scripts/get_folder.py 90100118193
uv run --python 3.14 scripts/get_folder.py 90100118193 --format summary
```

### get_custom_fields.py

List a list's custom fields, including option **UUIDs** needed for writes (reads return orderindex).

```bash
uv run --python 3.14 scripts/get_custom_fields.py 900600273627
uv run --python 3.14 scripts/get_custom_fields.py 900600273627 --format summary
```

### resolve_members.py

Resolve workspace members by name, email, or ID (MCP `clickup_resolve_assignees` / `find_member_by_name` / `get_workspace_members`).

> **Endpoint note:** ClickUp has **no** `GET /team/{team_id}/member` endpoint (it 404s). This uses `GET /team` and filters to the workspace's `members[]`. The static name→ID map in `create_task.py`/`update_task.py` stays the fast path; those scripts fall back here for names not in the map.

```bash
uv run --python 3.14 scripts/resolve_members.py "luke laughlin"   # name (substring)
uv run --python 3.14 scripts/resolve_members.py luke.mauldin@kidstrong.com
uv run --python 3.14 scripts/resolve_members.py --list             # all members
```

### get_workspace_hierarchy.py

Compose the spaces > folders > lists tree (MCP `clickup_get_workspace_hierarchy`).

```bash
uv run --python 3.14 scripts/get_workspace_hierarchy.py
uv run --python 3.14 scripts/get_workspace_hierarchy.py --space-id 16581563 --format summary
```

### docs.py

Read ClickUp Docs via the **v3** API. Doc write/create remain MCP-only.

```bash
# List a doc's pages (clickup_list_document_pages)
uv run --python 3.14 scripts/docs.py list-pages --doc-id c0pvq-10131

# Get page content as markdown (clickup_get_document_pages)
uv run --python 3.14 scripts/docs.py get-pages --doc-id c0pvq-10131 --content-format text/md

# A full doc URL also works (docId is parsed out)
uv run --python 3.14 scripts/docs.py list-pages --doc-id https://app.clickup.com/12606327/v/dc/c0pvq-10131/c0pvq-4511
```

### search.py

Keyword search (MCP `clickup_search`).

> **Limitation:** ClickUp's API has no free-text search endpoint. This is a **client-side substring scan** over task names (+ `--include-description`) and doc **titles** — no server-side relevance ranking, no comment search, doc bodies not searched. Scope with `--list/--space/--folder` to keep it fast; unscoped scans are bounded by `--max-pages`. For exhaustive custom-field filtering use `fetch_filtered_tasks.py`.

```bash
uv run --python 3.14 scripts/search.py "rate limiting"                 # whole workspace (bounded)
uv run --python 3.14 scripts/search.py "auth" --list 900600273627      # scoped (fast)
uv run --python 3.14 scripts/search.py "redis" --include-description --include-closed --no-docs
```

### task_relations.py

Add tags, links, and dependencies (mutations). Task IDs accept the `CU-` prefix.

```bash
# Add an existing tag (must already exist in the space)
uv run --python 3.14 scripts/task_relations.py add-tag 868abc123 backend

# Link two tasks
uv run --python 3.14 scripts/task_relations.py add-link 868abc123 868def456

# Dependencies: --depends-on (this waits for X) / --dependency-of (Y waits for this)
uv run --python 3.14 scripts/task_relations.py add-dependency 868abc123 --depends-on 868def456
uv run --python 3.14 scripts/task_relations.py remove-dependency 868abc123 --depends-on 868def456

# Preview any op without sending it
uv run --python 3.14 scripts/task_relations.py add-tag 868abc123 backend --dry-run
```

### delete_task.py

Delete task(s) — **destructive**. Dry-run by default; `--yes` is required to actually delete. Prints the task name before deleting.

```bash
uv run --python 3.14 scripts/delete_task.py 868abc123          # dry-run (default) — deletes nothing
uv run --python 3.14 scripts/delete_task.py 868abc123 --yes    # actually delete
```

### attach_file.py

Upload one or more **local files (by path)** to a task via ClickUp's native multipart attachment API. Unlike MCP `clickup_attach_task_file` (inline base64 or public URL only), this reads bytes straight from disk — no base64 round-trip through the model's context. Files upload sequentially (one request each); task IDs accept the `CU-` prefix.

```bash
# Attach a single file
uv run --python 3.14 scripts/attach_file.py 868abc123 ./report.md

# Attach multiple files (one request each)
uv run --python 3.14 scripts/attach_file.py 868abc123 ./a.md ./b.png ./c.pdf

# Custom task IDs (team_id required by the API in this mode)
uv run --python 3.14 scripts/attach_file.py CUSTOM-123 ./report.md \
  --custom-task-id --team-id 12606327

# Preview only — prints path, size, mimetype, target; sends nothing
uv run --python 3.14 scripts/attach_file.py 868abc123 ./report.md --dry-run
```

The returned `attachment_id` / `url` are printed per file; a non-zero exit means at least one upload (or path validation) failed. Max 1 GB per file; cloud-stored files are rejected by the API.

## MCP Tool Capabilities

For MCP tool parameters, workflows, and URL-to-ID parsing, see [references/mcp-workflows.md](references/mcp-workflows.md).

> **Note on tool names:** MCP tool names below use the ClickUp MCP server's canonical names. The actual invocation name depends on your MCP client (e.g., `mcp__clickup__clickup_search` in Claude Code). Search your available tools for `clickup` + the operation keyword if unsure.

### MCP Required (no script equivalent)

The 18 most-used tools now have scripts (see [references/mcp-coverage-matrix.md](references/mcp-coverage-matrix.md)). These remaining operations still **must** use MCP tools:
- **Document write/create** (`clickup_update_document_page` / `clickup_create_document` / `clickup_create_document_page`) - Doc *reads* are covered by `docs.py`; writes/creates remain MCP-only.
- **Chat** (`clickup_send_chat_message` / `clickup_get_chat_channels`) - Send/read chat messages
- **Time tracking** (`clickup_start_time_tracking` / `clickup_stop_time_tracking` / `clickup_add_time_entry`) - Start/stop/add time entries
- **Tag/link removal** (`clickup_remove_tag_from_task` / `clickup_remove_task_link`) - `task_relations.py` covers add-tag, add-link, and add/remove **dependency**; tag/link *removal* remain MCP-only.

### Both Work (selection depends on environment)

These can use either MCP or scripts:
- If `CLICKUP_API_TOKEN` is unavailable, use MCP for any operation in this section.
- If the token is available, prefer scripts when you specifically want their extra behavior.
- **Task read** - MCP `clickup_get_task` vs `get_task.py` (script has structured output, markdown desc)
- **Create task** - MCP `clickup_create_task` vs `create_task.py` (script has server team defaults)
- **Update task** - MCP `clickup_update_task` vs `update_task.py` (script has dry-run)
- **Add comment** - MCP `clickup_create_task_comment` vs `update_task.py --comment`
- **Get comments** - MCP `clickup_get_task_comments` vs `fetch_comments.py` (script has pagination)
- **Attach file** - MCP `clickup_attach_task_file` (inline base64 / public URL) vs `attach_file.py` (local file path, no base64 round-trip — prefer for files already on disk)

### Scripts Only (MCP can't do this)

Use scripts for these operations. These paths require `CLICKUP_API_TOKEN`; there is no MCP fallback documented in this skill for them:
- Filter by custom field values - `fetch_filtered_tasks.py`
- Get more than ~20 search results - `fetch_filtered_tasks.py`
- Bulk operations - `bulk_update_tasks.py`
- Resolve current sprint by date - `get_current_sprint.py`

## Backlog Grooming Workflow

This workflow is script-based and therefore requires `CLICKUP_API_TOKEN`.

### 1. Fetch Backlog
```bash
export CLICKUP_API_TOKEN="pk_..."
uv run --python 3.14 scripts/fetch_filtered_tasks.py --preset server -o backlog.json
```

### 2. Generate Review Docs
```bash
uv run --python 3.14 scripts/generate_ticket_docs.py backlog.json -o ./review \
  --flag-legacy --exclude-closed
```

### 3. Review in Editor
Open `./review/INDEX.md`, review tickets, mark decisions in grooming checkboxes.

### 4. Execute Decisions
```bash
# Close stale tickets
uv run --python 3.14 scripts/bulk_update_tasks.py close --ids-file to_close.txt \
  --comment "Closed during backlog grooming - no longer relevant"

# Update quarters
uv run --python 3.14 scripts/bulk_update_tasks.py update --ids-file q1_tasks.txt --quarter Q1
```

## Common Pitfalls

### Sprint Resolution Failures
`get_current_sprint.py` matches sprint list names against the current date. If no match is found (e.g., between sprints, or if the naming convention changed), it exits with an error. **Fix:** Use `--fallback latest` to select the most recent sprint by end date. Sprint names follow the pattern `Sprint NN (MM/DD - MM/DD)` or `Sprint NN (MM/DD/YY - MM/DD/YY)`.

### Custom Field Read vs. Write Asymmetry
Reading custom fields (from `get_task.py` output) returns `orderindex` (an integer like `0`, `1`, `2`). Writing custom fields via the API requires the option **UUID** (like `a1b2c3d4-...`). Always consult [references/custom-fields.md](references/custom-fields.md) for the UUID mapping before setting custom field values.

### Rate Limiting
`bulk_update_tasks.py` has a built-in 0.15s delay between API calls. When making manual API calls in loops (via MCP or direct API), add similar delays to avoid hitting ClickUp's rate limits. If you receive HTTP 429 responses, back off and retry.

### Comments Don't Support Markdown
The `comment_text` field renders markdown syntax as plain text. For formatted comments, use the structured JSON format. See [references/text-formatting.md](references/text-formatting.md).

### Task ID Prefix
ClickUp task IDs may appear with or without a `CU-` prefix (e.g., `CU-868abc123` vs `868abc123`). Scripts accept both formats. When extracting from branch names, use the regex `CU-([a-z0-9]+)`.

## Team Members

For bundled scripts, the `me` shortcut dynamically resolves to the current user based on your API token. For MCP tools, use the tool's assignee resolution support or the explicit user IDs below.

| Name | Shortcut | User ID |
|------|----------|---------|
| Current User | `me` | *(from API token)* |
| Luke Mauldin | `luke` | 75349906 |
| Bob D'Ercole | `bob` | 57214468 |
| Joshua Gasaway | `josh`, `joshua` | 38252373 |
| Rachel Vale | `rachel` | 38527352 |
