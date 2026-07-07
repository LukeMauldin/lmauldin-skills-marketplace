# MCP Tool Workflows

## Tool Naming

MCP tool names referenced below use the ClickUp MCP server's canonical names (e.g., `clickup_search`). Your actual tool invocation name depends on the MCP client:

| Client | Example Tool Name |
|--------|-------------------|
| Claude Code | `mcp__clickup__clickup_search` |
| Other clients | `clickup_search`, `clickup:search`, or similar |

**Discovery tip:** If unsure of the exact prefix, search your available tools for keywords like `clickup` + the operation name (e.g., `search`, `document`, `time`).

## Selection Rule

Use the toolchain that is actually available in the current session:

1. Prefer ClickUp MCP tools for any supported operation when `CLICKUP_API_TOKEN` is unavailable.
2. Switch to the bundled Python scripts only when you need script-only functionality or script-specific behavior and `CLICKUP_API_TOKEN` is present.
3. Do not invoke token-gated scripts as a first step if MCP can handle the request.
4. `generate_ticket_docs.py` is the main exception: it does not require `CLICKUP_API_TOKEN` unless `--fetch-comments` is used.

## Document Operations

### Reading a Document Page

ClickUp documents contain one or more pages. To read content, you need the document ID and page ID.

**Step 1: Parse the URL**

```
URL format: https://app.clickup.com/{workspaceId}/v/dc/{docId}/{pageId}
Example:    https://app.clickup.com/12606327/v/dc/c0pvq-36891/c0pvq-372151

Extract:
  docId  = c0pvq-36891
  pageId = c0pvq-372151
```

The `/v/dc/` path segment indicates a document view. See [workspace-structure.md](workspace-structure.md) for other URL patterns.

**Step 2: List pages (if you only have the doc ID, or need all pages)**

```
Tool: clickup_list_document_pages
Parameters:
  workspace_id: "12606327"
  document_id: "c0pvq-36891"

Returns: array of page objects with id, name, and ordering
```

**Step 3: Get page content**

```
Tool: clickup_get_document_pages
Parameters:
  workspace_id: "12606327"
  document_id: "c0pvq-36891"
  page_ids: ["c0pvq-372151"]         # array of page IDs to fetch
  content_format: "text/md"           # "text/md" for markdown, "text/html" for HTML

Returns: page content in the requested format
```

Prefer `text/md` for readability. Use `text/html` only when you need exact formatting fidelity.

### Updating a Document Page

```
Tool: clickup_update_document_page
Parameters:
  workspace_id: "12606327"
  document_id: "c0pvq-36891"
  page_id: "c0pvq-372151"
  content: "## Updated content\n\nNew markdown here."
  content_format: "text/md"           # must match the format of content you're providing
```

**Workflow: read-modify-write**
1. Get current content with `clickup_get_document_pages` using `content_format: "text/md"`
2. Modify the markdown content
3. Update with `clickup_update_document_page` using `content_format: "text/md"`

### Creating a Document

```
Tool: clickup_create_document
Parameters:
  workspace_id: "12606327"
  name: "Document Title"

Returns: document object with id
```

After creation, add pages with `clickup_create_document_page`:

```
Tool: clickup_create_document_page
Parameters:
  workspace_id: "12606327"
  document_id: "<new_doc_id>"
  name: "Page Title"
  content: "## Page content in markdown"
  content_format: "text/md"
```

## Search

### Keyword Search Across Workspace

```
Tool: clickup_search
Parameters:
  query: "rate limiting auth"         # keyword search string

Returns: tasks, docs, and other items matching the query
```

**Limitations vs. scripts:**
- Returns a limited result set (~20 items) — use `fetch_filtered_tasks.py` for exhaustive results
- Cannot filter by custom field values — use `fetch_filtered_tasks.py --custom-field` for that
- Searches across all item types (tasks, docs, comments) — useful for broad discovery

**When to use search vs. scripts:**
| Need | Use |
|------|-----|
| Quick keyword lookup | `clickup_search` |
| Find all tasks matching custom fields | `fetch_filtered_tasks.py` |
| Exhaustive results (100+ tasks) | `fetch_filtered_tasks.py` |
| Find a document by name | `clickup_search` |

## Time Tracking

### Check Current Timer

```
Tool: clickup_get_current_time_entry
Parameters:
  team_id: "12606327"
```

Returns the currently running timer (if any), including task ID, start time, and duration.

### Start a Timer

```
Tool: clickup_start_time_tracking
Parameters:
  team_id: "12606327"
  task_id: "868abc123"                # task to track time against
  description: "Working on auth fix"  # optional
  billable: false                     # optional

Note: Starts a new timer. Stops any currently running timer first.
```

### Stop Current Timer

```
Tool: clickup_stop_time_tracking
Parameters:
  team_id: "12606327"
```

### Add a Completed Time Entry

```
Tool: clickup_add_time_entry
Parameters:
  team_id: "12606327"
  task_id: "868abc123"
  start: 1704124800000                # ms epoch — start time
  duration: 3600000                   # ms — 1 hour
  description: "Code review"          # optional
  billable: false                     # optional
```

**Converting time values:**
- All timestamps are milliseconds since Unix epoch
- Duration is in milliseconds (1 hour = 3,600,000 ms)

### Get Time Entries for a Task

```
Tool: clickup_get_task_time_entries
Parameters:
  task_id: "868abc123"
```

## Tag Operations

### Add a Tag to a Task

```
Tool: clickup_add_tag_to_task
Parameters:
  task_id: "868abc123"
  tag_name: "backend"                 # existing tag name (case-sensitive)
```

### Remove a Tag from a Task

```
Tool: clickup_remove_tag_from_task
Parameters:
  task_id: "868abc123"
  tag_name: "backend"
```

Tags must already exist in the workspace. There is no MCP tool to create new tags — use the ClickUp UI or API directly.

## Chat Messages

### List Chat Channels

```
Tool: clickup_get_chat_channels
Parameters:
  workspace_id: "12606327"

Returns: list of chat channels with IDs and names
```

### Send a Chat Message

```
Tool: clickup_send_chat_message
Parameters:
  channel_id: "<channel_id>"          # from get_chat_channels
  content: "Deployment complete for config-service v1.2.3"
```

**Workflow:**
1. List channels with `clickup_get_chat_channels` to find the target channel ID
2. Send with `clickup_send_chat_message`

## Workspace Hierarchy Navigation

### Get Full Hierarchy

```
Tool: clickup_get_workspace_hierarchy
Parameters:
  team_id: "12606327"

Returns: full workspace tree — spaces, folders, lists
```

**When to use:** Only when you don't know the target space/folder/list ID. For known locations, use the IDs in [workspace-structure.md](workspace-structure.md) directly.

**Common use case — find a sprint list without the script:**
1. Call `clickup_get_workspace_hierarchy`
2. Navigate to Tech Space (`16581563`) → Server Sprint Folder (`90100118193`)
3. Find the list whose name matches the current date range

Prefer `get_current_sprint.py --team server --format id` when `CLICKUP_API_TOKEN` is available. If the token is unavailable, use the MCP hierarchy flow above.

## Task Operations (MCP vs. Script)

For task CRUD, both MCP tools and scripts work. Prefer MCP when `CLICKUP_API_TOKEN` is unavailable. Prefer scripts only when the token is present and you need server-team defaults or script-specific behavior.

| Operation | MCP Tool | Script | Prefer |
|-----------|----------|--------|--------|
| Get task | `clickup_get_task` | `get_task.py` | MCP if tokenless; script if you want structured output and markdown description |
| Create task | `clickup_create_task` | `create_task.py` | MCP if tokenless; script if you want auto sprint, auto assignee, and description template |
| Update task | `clickup_update_task` | `update_task.py` | Either; script when token is present and dry-run matters |
| Add comment | `clickup_create_task_comment` | `update_task.py --comment` | MCP if tokenless; either otherwise |
| Get comments | `clickup_get_task_comments` | `fetch_comments.py` | MCP if tokenless; script when token is present and pagination matters |

### MCP Task Operations — Quick Reference

**Get task:**
```
Tool: clickup_get_task
Parameters:
  task_id: "868abc123"
  include_markdown_description: true  # if supported
```

**Create task:**
```
Tool: clickup_create_task
Parameters:
  list_id: "<sprint_list_id>"         # resolve via get_current_sprint.py if token is available; otherwise use the hierarchy workflow above
  name: "Task title"
  markdown_description: "## Objective\n\n..."
  status: "Open"
  priority: 3                         # 1=urgent, 2=high, 3=normal, 4=low
  assignees: [75349906]               # user IDs
```

**Update task:**
```
Tool: clickup_update_task
Parameters:
  task_id: "868abc123"
  status: "in progress"
  priority: 2
```

**Add comment:**
```
Tool: clickup_create_task_comment
Parameters:
  task_id: "868abc123"
  comment_text: "Starting work on this"
```

**Get comments:**
```
Tool: clickup_get_task_comments
Parameters:
  task_id: "868abc123"

Returns: array of comment objects with text, author, and timestamp
```

For paginated comment fetching (large threads), prefer `fetch_comments.py --pages N`.

## Workspace Members

### Find a Member by Name

```
Tool: clickup_find_member_by_name
Parameters:
  workspace_id: "12606327"
  name: "Luke"                        # partial match supported
```

### List All Workspace Members

```
Tool: clickup_get_workspace_members
Parameters:
  workspace_id: "12606327"
```

## File Attachments

### Attach a File to a Task

```
Tool: clickup_attach_task_file
Parameters:
  task_id: "868abc123"
  file_path: "/path/to/file.png"
```

> **Prefer the script for local files.** `clickup_attach_task_file` accepts only inline
> base64 or a public URL — attaching an on-disk file forces the whole file through the
> model's context as base64. With `CLICKUP_API_TOKEN` set, use
> `scripts/attach_file.py <task_id> <file> [<file> ...]` instead: it streams bytes straight
> from disk via the native multipart endpoint (no base64 round-trip). See SKILL.md → `attach_file.py`.
