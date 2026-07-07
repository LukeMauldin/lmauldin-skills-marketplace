# JB Linear Admin Operations Appendix

Use this file only for lower-frequency operations (backlog grooming, workspace maintenance, and skill metadata upkeep). Daily create/update/search work should remain in `../SKILL.md`.

## Backlog Grooming Workflow

1. Resolve target team/project using the same project context rules from `../SKILL.md`.
2. List open issues with `list_issues` (`includeArchived: false`, high `limit`, paginate).
3. Exclude terminal states (`Done`, `Canceled`, `Duplicate`) unless auditing closures.
4. Fetch deeper detail with `get_issue` (`includeRelations: true`) for candidate issues.
5. Categorize and update in batches (independent calls in parallel).
6. Re-list to verify mutations.
7. Provide a concise summary of what changed and what was deferred.

## Priority Guidance (Admin Reference)

| Priority | Typical Use |
|----------|-------------|
| `1` Urgent | Production outage, data loss, security issue |
| `2` High | Functional blocker, customer-facing bug, dependency blocker |
| `3` Medium | Standard feature/improvement, non-blocking bug |
| `4` Low | Nice-to-have, polish, deferred work, technical debt |

## Label and Status Taxonomy Notes

Treat label/status data as live configuration, not static truth.

1. Always resolve labels from `list_issue_labels` for the target team.
2. Always resolve states from `list_issue_statuses` for the target team.
3. Do not rely on historical snapshots for mutation decisions.

Snapshot notes from `2026-02-28 UTC` may exist in historical skill content. Use them only as debugging hints.

## Project Context: `.linear/` Mirror

A project's context lives in a generated mirror committed to its own repo, produced by `/sync-linear-project`:

- `.linear/project.md` — Project ID, slug, URL, team, lead, initiative, state, target date, description.
- `.linear/team.md` — team details (client/customer, members); labels and statuses are resolved live, not mirrored.

Both are regenerated wholesale from Linear on each sync and are never hand-edited. The schema and generation steps are owned by the `/sync-linear-project` command (`../../../commands/sync-linear-project.md`); maintain them there, not here.

### Deprecated Central Docs

The `../projects/*.md` docs are **deprecated**, superseded by per-repo `.linear/`. Do not add new ones or extend existing ones. They are drained as each project is synced in its repo; the one repo-less project (`partners-real-estate`) remains until it acquires a repo or is retired.

## Admin Scripts

Scripts are maintenance utilities, not daily issue workflow tools.

- `../scripts/discover_linear_workspace.py`
  - Use to refresh workspace/project snapshot assumptions before structural edits to this skill.
  - Requires `LINEAR_API_KEY`.
- `../scripts/create_linear_labels.py`
  - Use for one-off or batch label administration.
  - Requires `LINEAR_API_KEY`.

For invocation details, run:

```sh
uv run jb-linear/scripts/discover_linear_workspace.py --help
uv run jb-linear/scripts/create_linear_labels.py --help
```

## Validation Checklist for Admin Changes

Before finalizing admin-level edits:

1. Confirm Linear tools are referenced by bare operation name (e.g. `get_project`), not a hardcoded namespace prefix — the prefix varies by runtime (see SKILL.md "Linear Tool Names").
2. Keep tool references prefix-free; `build.sh` does no namespace rewriting, so a hardcoded prefix ships verbatim and breaks on the runtimes that use a different one.
3. Confirm the `.linear/` schema and generation steps in `/sync-linear-project` still match live Linear field names.
4. Confirm no stale issue-count snapshots were introduced.
