# GCP Cost Analysis Skill

## Overview
Automated FinOps analysis for comparing GCP spending between time periods. The skill
queries BigQuery billing exports, correlates Cloud Run deployment activity, and
pulls git changes to help explain cost spikes.

## Billing Scope Model
- The billing export dataset lives in `ksu-live.tech_billing_data`.
- That dataset contains rows for multiple billed GCP projects via `project.id`.
- By default, the billing scripts analyze all exported projects in that dataset.
- Use `--project-filter` or `--project` only when you want to narrow cost analysis to one billed project such as `ksu-live` or `kidstrong-at-home`.
- Use `--bq-project` only to choose which GCP project executes the BigQuery job and has access to the billing dataset. It is not a billed-project filter.

## Prerequisites
- `gcloud` and `bq` CLI authenticated with access to target projects
- `uv` for running scripts
- Python 3.13+

## Quick Start
Generate a weekly report in one command:

```bash
uv run scripts/weekly_report.py \
  --target-start 2026-01-05 --target-end 2026-01-11 \
  --baseline-periods 2 --normalize-per-day
```

The command above compares costs across all projects exported into the billing dataset.

## Common Workflows

### Service and SKU Deltas
```bash
# Service-level across all exported projects
uv run scripts/cost_breakdown.py \
  --target-start 2026-01-05 --target-end 2026-01-11 \
  --baseline-periods 2 --normalize-per-day

# SKU-level with cost-type filtering across all exported projects
uv run scripts/cost_breakdown.py \
  --target-start 2026-01-05 --target-end 2026-01-11 \
  --by sku --exclude-tax-adjustments

# Project view to see which exported GCP projects drove the change
uv run scripts/cost_breakdown.py \
  --target-start 2026-01-05 --target-end 2026-01-11 \
  --by project

# Narrow the cost scope to one billed project in the export
uv run scripts/cost_breakdown.py \
  --target-start 2026-01-05 --target-end 2026-01-11 \
  --project-filter kidstrong-at-home
```

### Resource-Level Drivers
```bash
# All exported projects
uv run scripts/top_changes.py \
  --target-start 2026-01-05 --target-end 2026-01-11 \
  --baseline-periods 2 --min-delta 1.00

# One billed project only
uv run scripts/top_changes.py \
  --target-start 2026-01-05 --target-end 2026-01-11 \
  --project kidstrong-at-home
```

### Daily Trends and Anomalies
```bash
# All exported projects
uv run scripts/daily_costs.py \
  --start 2026-01-05 --end 2026-01-11 \
  --show-services --exclude-tax-adjustments

# One billed project only
uv run scripts/daily_costs.py \
  --start 2026-01-05 --end 2026-01-11 \
  --project ksu-live --show-services
```

### Deployment and Job Activity
```bash
uv run scripts/cloud_run_revisions.py \
  --start 2026-01-05 --end 2026-01-11 --all-projects
```

### Git Change Correlation
```bash
uv run scripts/git_deployments.py \
  --start 2026-01-05 --end 2026-01-11 \
  --repo /Users/lukemauldin/code/github.com/KidStrong/KidStrongBedrock
```

## Scripts Overview
| Script | Purpose |
|--------|---------|
| `weekly_report.py` | One-shot Markdown report (service/resource deltas + optional deployments/git) |
| `cost_breakdown.py` | Compare costs by service, SKU, or project |
| `top_changes.py` | Resource-level cost attribution |
| `daily_costs.py` | Daily cost trends, anomaly detection, and lag warning |
| `cloud_run_revisions.py` | Cloud Run revision timeline + config changes + job executions |
| `git_deployments.py` | Git commit summary for cost correlation |

## Output Notes
- **Credits Δ** shows how much of a cost change comes from credits shifting rather than usage.
- **Baseline periods**: `--baseline-periods N` averages the prior N periods for reference.
- **Per-day normalization**: `--normalize-per-day` is recommended when periods differ in length.
- **Cost types**: use `--exclude-tax-adjustments` or `--cost-type/--exclude-cost-type` to control cost types.
- **Project scope**: billing scripts default to all `project.id` values present in the export unless you add a project filter.
- **BigQuery host**: `--bq-project` controls where the query runs, not which billed projects are included.

## Date Range Behavior
Dates are inclusive. For example, 2026-01-05 to 2026-01-11 is 7 days.

## Defaults
- Bedrock repo: `/Users/lukemauldin/code/github.com/KidStrong/KidStrongBedrock`
- Terraform repo: `/Users/lukemauldin/code/github.com/KidStrong/tf-main-apps`
