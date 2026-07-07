---
name: dev-status-tracker
description: Generate unified ClickUp/GitHub/GCP status reports for KidStrong server sprint work by linking ClickUp tasks to GitHub PRs and Cloud Run deployments, detecting status mismatches, missing ClickUp IDs at end of PR titles, and multi-service deployment gaps. Use when auditing current sprint progress or producing a markdown report of true merged/deployed state across ClickUp, GitHub Actions, and GCP.
---

# Dev Status Tracker Codex

Generate a unified status report across ClickUp, GitHub PRs, and GCP Cloud Run deployments.

## Requirements

- Python 3.14+ (use `uv run --python 3.14`)
- `gh` CLI (authenticated)
- `gcloud` CLI (authenticated, optional)

**Python packages:** None required (stdlib only)

## LLM Instructions

When generating reports, write output files to `docs/reports/` in the `ks-pm` repo by default (e.g., `--output docs/reports/dev-status-sprint84.md`). Use the naming convention `dev-status-sprint{N}.md`.

## Bundled Scripts

This skill includes the following script in its `scripts/` directory:

- `scripts/generate_status_report.py` - Main report generator that queries ClickUp, GitHub, and GCP **(EXECUTE, do not read into context)**

All script paths below are **relative to this skill's directory**. Execute with:

```bash
uv run --python 3.14 scripts/generate_status_report.py [options]
```

## Quick Start

1. Export ClickUp token:

```bash
export CLICKUP_API_TOKEN="pk_..."
```

2. Run the report for the current sprint:

```bash
uv run --python 3.14 scripts/generate_status_report.py
```

The script auto-resolves the current sprint list ID and name from ClickUp.

To switch sprint folders:

```bash
uv run --python 3.14 scripts/generate_status_report.py --sprint-folder coach
```

3. Save to a file:

```bash
uv run --python 3.14 scripts/generate_status_report.py --output ~/Desktop/dev-status.md
```

4. Use remote workflow discovery across multiple repos:

```bash
uv run --python 3.14 scripts/generate_status_report.py \
  --repos KidStrongBedrock bedrock-protos tf-main-apps \
  --workflow-source remote
```

## Defaults

- ClickUp list: Auto-resolve current sprint from selected sprint folder (default: server)
- GitHub org: `KidStrong`
- GitHub repo(s): `KidStrongBedrock`
- Repo path for workflow discovery: `~/code/github.com/KidStrong/KidStrongBedrock`
- Workflow discovery source: `auto` (local if path exists, otherwise remote)
- GCP projects: `kidstrong-at-home` (dev), `ksu-live` (prod)
- Cloud Run region: `us-central1`

## External Skill Dependencies

This skill requires the **clickup-engineer** skill to be installed as a sibling in the same skills directory:

```
<skills-root>/
├── dev-status-tracker/    ← this skill
│   └── scripts/generate_status_report.py
└── clickup-engineer/      ← required sibling skill
    └── scripts/
        ├── get_current_sprint.py
        ├── get_list.py
        ├── fetch_filtered_tasks.py
        ├── get_task.py
        └── fetch_comments.py
```

Alternatively, set `CLICKUP_ENGINEER_PATH` to a custom location.

## Status Mapping

Use these expectations when comparing ClickUp to GitHub/GCP:

| Observed State | Expected ClickUp Status |
|---|---|
| PR open (not merged) | `in review` |
| PR merged, prod not deployed, QA **not** approved | `testing` |
| PR merged, prod not deployed, QA approved | `pending live` |
| PR merged, prod deployed | `completed` |

**Note:** Closed (abandoned/superseded) PRs are excluded from status inference. Only open and merged PRs affect the expected status. A task with only closed PRs is treated the same as a task with no PRs.

## QA Approval Detection

Detect QA approval by scanning task comments for a default regex:

```
qa approved | approved qa | qa pass | passed qa | qa ok | qa complete | qa sign-off
| approved for prod/production | ready for prod/production | tested and approved
```

Comment retrieval uses `clickup-engineer/scripts/fetch_comments.py` with `--pages` tied to `--comment-pages`.

Override if needed:

```bash
uv run --python 3.14 scripts/generate_status_report.py --qa-approval-regex "qa\s*approved|qa\s*signoff"
```

## Workflow Mapping and GCP Checks

- Parse `.github/workflows/*.yml` and `.github/workflows/*.yaml` to map workflow name → service/job name.
- If a local repo is not available, fetch workflow files via `gh api` using `--workflow-source remote` (or `auto` to fall back).
- Use `--workflow-ref` to read workflows from a specific branch or commit.
- Use GitHub Actions runs for the merge commit to find deploy workflows.
- When mapping is available, query Cloud Run services/jobs for `commit-sha` labels to verify dev/prod deployment.
- If a workflow cannot be mapped to a service/job, GCP lookups are skipped and the report notes the reason.

Skip GCP lookups if needed:

```bash
uv run --python 3.14 scripts/generate_status_report.py --skip-gcp
```

## Report Layout

1. **Discrepancies**: ClickUp status does not match GitHub/GCP state.
2. **Issues**: Data quality problems (missing PRs, workflow mapping gaps).
3. **Tasks**: All tasks in ClickUp list order with PR/deploy details and issues.
4. **Summary**: Counts of discrepancies, issues, and OK tasks.

## Command Options

- `--list-id`: ClickUp list ID (omit to auto-resolve current sprint)
- `--list-name`: Override list name for report header
- `--sprint-folder`: Sprint folder to use when auto-resolving (`server`, `coach`, `tv`)
- `--repos`: Space/comma-separated repo names
- `--repo-path`: Local repo path for workflow discovery
- `--repo-paths`: Repo-to-path overrides (e.g., `OtherRepo=/path/to/other`)
- `--workflow-source`: `auto`, `local`, or `remote` workflow discovery
- `--workflow-ref`: Git ref to use when reading remote workflow files
- `--task-ids`: Limit to specific ClickUp task IDs
- `--output`: Write markdown to a file
- `--json`: Emit raw JSON instead of markdown
- `--comment-pages`: Scan additional ClickUp comment pages for QA approval
- `--qa-approval-regex`: Override QA approval detection
- `--skip-gcp`: Use GitHub Actions only
- `--since DAYS`: Only search PRs updated within the last N days (default: 90)
- `--no-since`: Disable date filtering, search all PRs

## Verification

After generating a report:

1. Confirm the output file exists at the specified path
2. Spot-check 2-3 tasks to verify PR links are correct
3. If discrepancies seem wrong, verify ClickUp API token has list access
4. Re-run with `--task-ids` on a single task for targeted debugging

## Troubleshooting

| Error | Cause | Solution |
|-------|-------|----------|
| `gh: command not found` | GitHub CLI not installed | `brew install gh && gh auth login` |
| `CLICKUP_API_TOKEN not set` | Missing env var | `export CLICKUP_API_TOKEN="pk_..."` |
| `clickup-engineer scripts not found` | Sibling skill missing | Install clickup-engineer skill or set `CLICKUP_ENGINEER_PATH` |
| `gcloud: command not found` | GCP CLI not installed | Use `--skip-gcp` or install gcloud |
| No PRs found for task | PR title missing `CU-<id>` | Ensure PR title contains `CU-<taskid>` |
| Workflow mapping failed | Service name uses variables | GCP checks skipped; verify manually |

## Example

Validate the sample task/PR pairing:

```bash
uv run --python 3.14 scripts/generate_status_report.py --task-ids 868gn68e8
```

Expect to see PR #1533 and deploy workflows for `kidstrong-switchboard` and `kidstrong-nexus`.
