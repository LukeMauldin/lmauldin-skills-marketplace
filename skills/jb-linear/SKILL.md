---
name: jb-linear
description: Manage Linear issues across JB Web projects. ALWAYS use this skill for any Linear operation — direct MCP calls return full issue bodies that bloat context. Use when creating, updating, commenting on, searching issues, or when a Linear issue ID is referenced as the basis for a task. Also activates when the user asks to work on, fix, or implement a tracked issue.
---

# JB Web Linear Issue Management

## Overview

Three common workflows:

1. Create an issue
2. Update an issue (including comments)
3. Search/list issues

## Linear Tool Names

Linear tools are named here by their **bare operation** (`get_project`, `list_issues`, `save_issue`, `create_comment`, …). The MCP namespace prefix differs by runtime, so do not hardcode it: Claude Code exposes `mcp__linear-server__*`, claude.ai exposes `mcp__claude_ai_Linear__*`, Codex exposes `mcp__linear__*`. Match the operation name against whichever Linear MCP server is connected and call that tool.

## Project Context: per-repo `.linear/`

The source of truth for a project's identity is a generated mirror committed to the **project's own repo**:

- `.linear/project.md` — Project ID, name, description, lead, state, initiative(s), team.
- `.linear/team.md` — team details (client/customer, members). Labels and statuses are resolved live, not mirrored.

Both are regenerated wholesale from Linear by `/sync-linear-project` run inside the repo. They are never hand-edited. When working in a repo, read `.linear/project.md` for the canonical Project ID before any mutation. See Project Context Resolution.

**Runtime note.** `.linear/`, `/sync-linear-project`, and git detection all require a local working tree — they apply in **Claude Code** only. In **claude.ai** (and any environment without a filesystem) there is no repo to read: Linear is consulted live every time, so there is nothing to cache and nothing to go stale. Project guidance that used to live in central docs belongs in the **Linear project description**, which `get_project` returns live. Do not attempt `git`/file probes when no filesystem is available — resolve the project directly from Linear.

### Transitional central docs

The `projects/*.md` reference docs are **deprecated** — superseded by per-repo `.linear/`. They remain only as a fallback for repos not yet migrated, and for `partners-real-estate`, which has no code repo. Each is drained the next time `/sync-linear-project` runs in its repo. Do not extend them.

- [Admin Operations Appendix](references/admin-operations.md) — use only for backlog/admin/maintenance tasks

## Core Operating Rules

1. Resolve team and project to **stable IDs** before mutation. Pass the project's UUID — never its display name — to `save_issue`. Name-matching is silently lossy: a mismatched name is accepted as a no-op and the issue lands with no project. See Project Context Resolution.
2. Search for likely duplicates before creating a new issue.
3. Do not silently set project to "No Project"; require explicit user confirmation.
4. Always validate status and labels against the target team before mutation.
5. `labels`, `relatedTo`, `blockedBy`, and `blocks` are replacement arrays. Fetch, merge, then save.
6. Validate create/update writes with a follow-up `get_issue` and confirm the returned project name matches the intent.
7. Run independent read calls in parallel when possible.
8. Do not infer primary team from multi-team project ordering; confirm when ambiguous.
9. AI actions must be visibly attributed. See AI Attribution Rules below.
10. Transition issues between states as work progresses. See Status Transitions below.
11. When a fix resolves or relates to multiple issues, link them and annotate both with commit SHAs. See Cross-Issue Linking below.
12. Do not adjust an issue's priority based on comments. Priority changes require explicit user instruction.

## AI Attribution Rules

### When Transitioning to Done

Before transitioning to **Done**, in this order:

1. **Commit any uncommitted changes.** Run `git status` — if related files are staged or modified, commit them before closing. Do not leave work uncommitted when marking an issue done.
2. **Add an attribution comment** that includes:
   - That closure was performed by an AI agent
   - A brief summary of what was done
   - The commit SHA(s) or branch name

Example comment:
> **Closed by AI agent.** Added human-in-the-loop boundaries section to the ai-guardrail skill. Branch: `skill-builder-and-guardrails`, commit: `8267300`.

3. **Transition the status** to Done.

Do not close without the attribution comment. Do not close with uncommitted changes.

**Do not add attribution comments when transitioning to In Progress or In Review.** The activity log records those changes automatically.

### When Creating an Issue

Append to the description:
> *This issue was created by AI as part of [context].*

### When Updating an Issue

Routine field updates (priority, labels, assignee, status) need no special attribution — the activity log records the change. For substantive description rewrites, add a comment noting what changed and why.

## Status Transitions

Transition without waiting to be asked. Use this table to decide:

| Target state | Trigger | Constraint |
|---|---|---|
| **Todo** | User provides a list of Backlog issues to work on | Move all listed issues from Backlog → Todo immediately. Do not wait until work begins. |
| **In Progress** | You begin executing: writing code, making edits, running commands that address the issue | Default: transition. When in doubt, transition. |
| **In Review** | Implementation complete from your side: commits ready, PR created, or work handed back to human review | Prefer over jumping straight to Done — this is the default end state for AI work |
| **Done** | User explicitly confirms: "close it", "mark it done", PR approved | Never self-close. Always add attribution comment first. |

### How to Transition

1. `list_issue_statuses` for the target team to get the exact status ID.
2. `save_issue` with the `state` field set to the target status.
3. Verify with `get_issue`.

## Cross-Issue Linking

When a single fix addresses more than one issue, connect them explicitly.

**Relation types:** `duplicate` (same problem), `related` (partially addresses another), `blocks`/`blockedBy` (directional dependency). Default to `related` if unsure.

**How to link:**
1. `get_issue` on both issues with `includeRelations: true`.
2. Determine relation type, merge into existing arrays (replacement arrays — Core Rule #5).
3. `save_issue` with merged arrays on both issues.
4. Add a comment to both issues: relation, commit SHA, one-line summary.

Example comment:
> Related to AIGD-60. Commit `73538c6` on `skill-builder-and-guardrails` also satisfies this issue's acceptance criteria.

Only link when there is a genuine connection.

## Project Context Resolution

Project names in Linear are mutable and can drift. To prevent silent project loss on writes, resolve to a stable **Project ID (UUID)** and pass that ID to `save_issue`. Use this order of precedence.

**First, branch on runtime.** If there is a local working tree (Claude Code), use the full order below. If there is no filesystem (claude.ai or similar), the repo-bound steps (2 local `.linear/`, and git-remote matching in 3) do not apply — use **step 1**, then the name-matched central-doc path in **step 3**, then the live **step 4 fallback**. Never run `git`/file probes where no filesystem exists.

### 1. Explicit User Context
If the user gives team/project/issue ID explicitly, use it directly. For a Linear project URL of the form `linear.app/<org>/project/<slug>-<short-id>/...`, pass the `<slug>-<short-id>` path segment straight to `get_project` (`query=...`) — it returns the full record including the UUID in one call. Fall back to `list_projects` only if `get_project` cannot resolve it. Pass the returned UUID to mutation calls.

### 2. Local `.linear/project.md`
The primary mechanism. Check the repo root (`git rev-parse --show-toplevel`) for `.linear/project.md`. If present, read the **Project ID** from it and use that UUID for all mutations; read `.linear/team.md` for the client (labels and statuses are resolved live, not mirrored). These are generated mirrors of Linear — trust the Project ID as the stable key even if a recorded name looks stale, and suggest `/sync-linear-project` if the data appears out of date.

If the repo has no `.linear/` at all, the project has not been onboarded — offer to run `/sync-linear-project` to create it.

### 3. Transitional Central Docs (deprecated)
Bundled `projects/*.md` docs, readable in any runtime (they ship in the skill). To find the matching doc, scan the docs' own identifying fields — in Claude Code, match `git remote -v` against each doc's **Repository Mapping**; in claude.ai, match the project name against each doc's title. (There is no separate remote→doc index; the docs are self-identifying, and the scan shrinks as they drain.) Each holds a **Project ID (UUID)** under Project Defaults — use that UUID for mutations. In Claude Code, recommend `/sync-linear-project` to migrate the repo to `.linear/`. When no doc matches, go to the live fallback. The repo-less `partners-real-estate` lives here until it acquires a repo.

### 4. Fallback
1. Resolve/confirm target team.
2. `list_projects` for that team.
3. Auto-select only if confidence is high (single obvious candidate); otherwise present top 2-3 and require user selection.
4. Capture the resolved project's UUID before any write.

### 5. Preflight Validation Before Create/Update

1. `list_teams` — capture the target team's UUID.
2. `list_projects` (filtered by team) — capture the target project's UUID. If `.linear/project.md` or a transitional central doc lists a Project ID, prefer that ID and confirm it still exists by ID (not by name).
3. `list_users` (if setting assignee).
4. `list_issue_statuses` (target team).
5. `list_issue_labels` (target team).

If any default cannot be resolved, ask before continuing. If a recorded project name (in `.linear/project.md` or a transitional central doc) no longer matches the live Linear name but the ID still resolves, proceed with the ID and surface the drift in the output, recommending `/sync-linear-project` to regenerate the local mirror.

## Fast Path 1: Create Issue

**Required fields:** `title`, `team` (UUID), `project` (UUID — or explicit confirmation to omit)

1. Resolve project context to a **Project ID (UUID)** per Project Context Resolution.
2. Duplicate check: `list_issues` with `team`, `project` (UUID), keyword `query`.
3. If likely duplicate found, ask whether to update the existing issue instead.
4. `save_issue` with `project` set to the **UUID**, not the display name. Passing a name that doesn't match exactly is accepted silently and the project field ends up empty.
5. Verify via `get_issue` and confirm the returned project name matches the intended project.

**Defaults:** Priority = Medium (`3`). Assignee = Unassigned — leave new issues with no assignee unless the user names one (the `Default Assignee` in `.linear/project.md` is `Unassigned`).

**Label policy:** Apply only **Dev Type**, **Dev Area**, and **Security** labels; leave a group unset when the right label is ambiguous. Resolve the live set with `list_issue_labels` before writing (Preflight step 5). Full taxonomy, apply policy, and per-label engineering approach: [Labels reference](references/labels.md).

**Title conventions:**

| Type | Pattern | Good | Bad |
|---|---|---|---|
| Task | Present tense imperative | "Add dropdown list to the left side of the screen" | "Added dropdown" / "Dropdown" |
| Bug | Present tense, procedural | "Page scroll fails when light mode is selected" | "Scroll broken" |
| User story | Role + activity | "As an administrator I'd like to bulk-assign issues" | "Bulk assign feature" |

Never prefix titles with category words (Bug, Fix, Feature, Task, Chore, etc.) — labels and type fields exist for that. A longer title is fine if it's genuinely descriptive.

**Description:** For non-trivial work include: outcome summary, problem/context, acceptance criteria. End all AI-created descriptions with the AI attribution note.

## Fast Path 2: Update Issue and Comments

Use issue identifier (`RF-123`, UUID) whenever possible.

**Comment only:** `create_comment` with `issueId` and markdown `body`.

**Field update:**
1. `get_issue` (`includeRelations: true`)
2. Merge requested changes with current arrays
3. If transitioning to Done: add attribution comment first
4. `save_issue` with full replacement arrays
5. Verify with `get_issue`

Never send partial replacement arrays (`labels`, `relatedTo`, `blockedBy`, `blocks`) unintentionally.

## Fast Path 3: Search and List Issues

1. Exact lookup: `get_issue` with ID
2. Keyword search: `list_issues` with `team`, optional `project`, `query`
3. Work queue: `list_issues` with filters (`assignee`, `state`, `priority`, `project`)

Constrain by team whenever known. Constrain by project for duplicate checks. Use multiple short keyword passes rather than one long query. Paginate large result sets until `hasNextPage` is false.

## Output Contract

After any operation, report:
1. What changed (issue IDs + one-line summary)
2. Defaults/assumptions used
3. Resolved project/team context — include the **project name returned by Linear** (from the verification `get_issue`), not the name you intended. A mismatch between intent and Linear's returned name indicates either a silent project drop or a project rename; surface it.
4. Any risks or follow-ups, including any detected rename of a project relative to its reference doc.

## Slash Commands

- **`/sync-linear-project`** — Run inside a project repo to link it to its Linear project and generate/refresh the `.linear/project.md` + `.linear/team.md` mirror. Onboards a new repo, re-syncs an existing one, and surfaces migration notices for projects still on the deprecated central docs.

## Admin Appendix

Load [Admin Operations Appendix](references/admin-operations.md) only for: backlog grooming, workspace label/status taxonomy work, or skill maintenance for project reference docs.
