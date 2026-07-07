# KidStrong ClickUp Workspace Structure

## Workspace

| Field | Value |
|-------|-------|
| Workspace Name | KidStrong |
| Workspace ID | `12606327` |

## Tech Space

The primary space for engineering work.

| Field | Value |
|-------|-------|
| Space Name | Tech |
| Space ID | `16581563` |

### Tech Space Folders

| Folder | ID | Purpose |
|--------|-----|---------|
| Coach Sprint Folder | `90100118119` | KS Coach app sprint work |
| TV Sprint Folder | `90100118129` | KSTV app sprint work |
| Server Sprint Folder | `90100118193` | Backend server sprint work |
| Lighthouse | `90115997332` | Lighthouse admin tool |
| Release Notes | `90112222666` | Release documentation |
| Design | `90112038771` | Design assets |
| Product | `90115506809` | Product team items |
| Tech Projects | `90112013034` | Cross-team projects |
| **Tech Roadmap** | `90060144434` | **Main backlog location** |
| Tech Documents | `90111706074` | Technical documentation |
| Tech Templates | `90112222646` | Templates |
| Policy and Process | `90112222585` | Policies |
| L10 Leads Meeting | `90111780116` | Leadership meeting items |
| Product Surveys | `90112333436` | Feedback collection |
| KSTV Tech Proposals | `90115573948` | KSTV proposals |

### Key Lists

#### Product Roadmap (Primary Backlog)

| Field | Value |
|-------|-------|
| List Name | Product Roadmap |
| List ID | `900600273627` |
| Parent Folder | Tech Roadmap (`90060144434`) |
| Purpose | Main backlog for all apps (Server, Coach, TV, etc.) |

**Views in Product Roadmap:**
- Quarterly Roadmap
- Board
- Server Backlog (filtered: Apps = Server)
- KSC Backlog (filtered: Apps = KS Coach)
- + others

#### Server Team Sprint Structure

**Sprint Cadence:** 2-week sprints (Sunday to Saturday)
**Sprint Folder:** Server Sprint Folder (`90100118193`)
**Board View:** `https://app.clickup.com/12606327/v/b/li/{list_id}?pr=16581563`

**Sprint List Naming Convention:** `Sprint {number} ({MM/DD} - {MM/DD})` or `Sprint {number} ({MM/DD/YY} - {MM/DD/YY})`

| Pattern | Example |
|---------|---------|
| Short date format | `Sprint 77 (12/15 - 12/28)` |
| Full date format | `Sprint 78 (12/29/25 - 1/11/26)` |

**Always resolve dynamically:** `uv run --python 3.14 scripts/get_current_sprint.py --team server --format id`

**Finding Current Sprint:**
Sprint list IDs change each sprint. To find the current sprint:
1. Use `uv run --python 3.14 scripts/get_current_sprint.py --team server --format id`
2. (Fallback) Use the `get_workspace_hierarchy` MCP tool with `space_ids=["16581563"]`
3. Look for Server Sprint Folder children
4. Current sprint will have the most recent date range

#### Coach Sprint Lists

Located in Coach Sprint Folder (`90100118119`).

**Resolve dynamically:** `uv run --python 3.14 scripts/get_current_sprint.py --team coach --format id`

#### TV Sprint Lists

Located in TV Sprint Folder (`90100118129`).

**Resolve dynamically:** `uv run --python 3.14 scripts/get_current_sprint.py --team tv --format id`

## Other Spaces

| Space | ID | Purpose |
|-------|-----|---------|
| Analytics | `90110475975` | Analytics team |
| Programming | `90110595477` | Content programming |
| Customer Support | `90110954762` | Support tickets |
| Web 2.0 | `90110639796` | Web team |
| NCO | `90110792400` | New center openings |

## Task ID Formats

ClickUp task IDs can appear in several formats:

| Format | Example | Notes |
|--------|---------|-------|
| Standard | `868fn77az` | 9-character alphanumeric |
| With prefix | `CU-868fn77az` | Same ID with CU- prefix |
| In URL | `/t/868fn77az` | Embedded in task URL |

**All formats refer to the same task.** When extracting from URLs or branch names, strip the `CU-` prefix if present.

### Task ID in Git Branch Names

Common patterns for extracting ClickUp task IDs from branch names:

| Pattern | Example | Extract |
|---------|---------|---------|
| Suffix with underscore | `tickets/Fix_redirect_CU-868g0ntq8` | `868g0ntq8` |
| Suffix with underscore | `feature/some-work_CU-868abc123` | `868abc123` |
| Just ID | `feature/868abc123-fix-bug` | `868abc123` |

**Regex pattern:** `CU-([a-z0-9]+)` or `([a-z0-9]{9})` at end of branch name.

## URL Patterns

### Task URLs

```
# Full URL pattern
https://app.clickup.com/t/{taskId}

# Example
https://app.clickup.com/t/868fn77az
→ Extract task_id: 868fn77az
→ Use: get_task.py 868fn77az
→ Or:  clickup_get_task(task_id="868fn77az")
```

### Document/Page URLs

```
# Full URL pattern
https://app.clickup.com/{workspaceId}/v/{viewType}/{docId}/{pageId}

# Example
https://app.clickup.com/12606327/v/dc/c0pvq-36891/c0pvq-372151
→ Extract: workspaceId=12606327, viewType=dc, docId=c0pvq-36891, pageId=c0pvq-372151
→ Use: clickup_get_document_pages(document_id="c0pvq-36891", page_ids=["c0pvq-372151"])
```

**View type codes:**
- `dc` = Document
- `l` = List view
- `b` = Board view

### List/Board URLs

```
# List view
https://app.clickup.com/12606327/v/l/{list_id}

# Board view (sprint boards)
https://app.clickup.com/12606327/v/b/li/{list_id}?pr=16581563

# Saved view
https://app.clickup.com/12606327/v/l/{view_id}
```

### Workspace URLs

```
# Workspace home
https://app.clickup.com/12606327/home
```

## API Endpoints

```
Base URL: https://api.clickup.com/api/v2

# Get workspace hierarchy
GET  /team/12606327/space?archived=false

# Get tasks with filters
GET  /team/12606327/task?list_ids[]=900600273627&custom_fields=[...]

# Get single task
GET  /task/{task_id}

# Update task
PUT  /task/{task_id}

# Get task comments
GET  /task/{task_id}/comment

# Add comment
POST /task/{task_id}/comment

# Set custom field value
POST /task/{task_id}/field/{field_id}

# Move task to list
POST /list/{list_id}/task/{task_id}
```

For the full OpenAPI spec (80 endpoints), see [clickup-api-v2.json](clickup-api-v2.json).
