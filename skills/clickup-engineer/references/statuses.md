# Server Sprint Statuses

Statuses defined on the Server Sprint Folder (`90100118193`). These apply to all sprint lists within the folder.

## Status Workflow

```
Open → in progress → in review → testing → pending live → completed → Closed
                                    ↓
                               blocked (can return to any stage)
```

## Status Reference

| Status | ID | Type | Color | Order |
|--------|-----|------|-------|-------|
| Open | `c90100118193_A8a81mwS` | open | `#87909e` | 0 |
| in progress | `c90100118193_Avibb2NB` | custom | `#4466ff` | 1 |
| in review | `c90100118193_c4axKNkQ` | custom | `#e16b16` | 2 |
| testing | `c90100118193_sHFzr8ri` | custom | `#f8ae00` | 3 |
| blocked | `c90100118193_8XPCYxA3` | custom | `#5f55ee` | 4 |
| pending live | `c90100118193_8ZzHnHyZ` | done | `#ee5e99` | 5 |
| completed | `c90100118193_8ZzHnHyZ` | done | `#000000` | 6 |
| Closed | `c90100118193_mjmqtBYv` | closed | `#008844` | 7 |

## Status Types

- **open**: Initial/default status for new tasks
- **custom**: Intermediate workflow statuses
- **done**: Task is finished but not officially closed
- **closed**: Task is complete and closed

## Usage in API

When creating or updating tasks, use the **status name** (case-insensitive):

```python
# Create task with status
task_data = {
    "name": "My task",
    "status": "Open"  # or "in progress", "testing", etc.
}

# Update task status
update_data = {
    "status": "in progress"
}
```

## Notes

- Status names are case-insensitive in API calls
- "Open" and "Closed" are capitalized, others are lowercase
- The status group `cat_90100118193` is shared across all sprint lists in the Server Sprint Folder
- Product Roadmap list may have different statuses (check list-specific statuses if needed)
- **Known issue:** `pending live` and `completed` share the same ID (`c90100118193_8ZzHnHyZ`) in the ClickUp API response. When targeting these statuses, use the **status name** (not ID) to avoid ambiguity
