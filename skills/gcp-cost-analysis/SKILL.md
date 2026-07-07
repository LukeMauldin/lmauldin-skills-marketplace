---
name: gcp-cost-analysis
description: >
  Comprehensive GCP FinOps cost analysis skill for comparing cloud spending between time periods.
  Use when investigating cost spikes, anomalies, or trends. Analyzes BigQuery billing data,
  Cloud Run deployments, git history, and correlates with log analysis using gcp-log-analysis skill.
  Produces executive summaries with actionable recommendations.
---

# GCP Cost Analysis

Comprehensive FinOps analysis for GCP cost investigation. This skill analyzes billing data,
deployment activity, and code changes to identify root causes of spending anomalies.

## When to Use This Skill

- Investigating cost spikes or unexpected spending increases
- Comparing costs between time periods (week-over-week, month-over-month)
- Identifying top cost drivers and resource-level attribution
- Correlating infrastructure changes with cost fluctuations
- Producing FinOps reports for stakeholders

## Prerequisites

- **uv**: Python package manager ([install](https://docs.astral.sh/uv/))
- **bq CLI**: BigQuery command-line tool (part of gcloud SDK)
- **gcloud CLI**: Authenticated with access to target projects
- **Python 3.13+**: Required by script inline metadata (PEP 723)

```bash
# Verify prerequisites
gcloud auth login
bq ls ksu-live:tech_billing_data  # Should list billing tables
```

## Billing Scope Model

This skill uses billing export tables hosted in `ksu-live.tech_billing_data`, but
those tables contain rows for multiple billed GCP projects via `project.id`.

- `--bq-project` selects the GCP project that runs the BigQuery job and has access
  to the dataset. It does **not** limit cost scope.
- Billing scripts analyze **all exported projects by default**.
- Use `--project-filter` or `--project` only when you need to narrow analysis to
  one billed project such as `ksu-live` or `kidstrong-at-home`.
- `--by project` is the quickest way to see which exported projects drove a change.

## User Input Format

When the user invokes this skill, they should provide:

1. **Target Period**: The time frame to analyze (e.g., "1/5/2026 through 1/11/2026")
2. **Reference Period**: The baseline for comparison (optional - defaults to period before target)
3. **Focus Areas** (optional): Specific services, projects, or concerns

Example invocations:
- "Analyze GCP costs for 1/5/2026 to 1/11/2026 compared to the previous week"
- "Why did costs increase 20% last week? Compare 1/5-1/11 to 12/29-1/4"
- "Investigate Cloud Run cost spike between January 5-11"
- "Compare all KidStrong projects in the billing export for 1/5/2026 to 1/11/2026"
- "Analyze ksu-live only, but run the BigQuery query from ksu-live.tech_billing_data"

## Analysis Workflow

Follow this structured workflow when performing cost analysis:

### Phase 1: Data Collection (Run in Parallel)

Execute these scripts simultaneously to gather baseline data:

```bash
SKILL_DIR="/Users/lukemauldin/.claude/skills/gcp-cost-analysis"

# 1. Service-level cost breakdown
uv run $SKILL_DIR/scripts/cost_breakdown.py \
  --target-start YYYY-MM-DD --target-end YYYY-MM-DD \
  --reference-start YYYY-MM-DD --reference-end YYYY-MM-DD \
  --by service --baseline-periods 2 --normalize-per-day --exclude-tax-adjustments

# 2. SKU-level cost breakdown (more granular)
uv run $SKILL_DIR/scripts/cost_breakdown.py \
  --target-start YYYY-MM-DD --target-end YYYY-MM-DD \
  --by sku --limit 30 --baseline-periods 2

# 2b. Project-level breakdown across all exported GCP projects
uv run $SKILL_DIR/scripts/cost_breakdown.py \
  --target-start YYYY-MM-DD --target-end YYYY-MM-DD \
  --by project --baseline-periods 2

# 3. Daily cost trends
uv run $SKILL_DIR/scripts/daily_costs.py \
  --start YYYY-MM-DD --end YYYY-MM-DD \
  --show-services --exclude-tax-adjustments

# 4. Cloud Run deployments during period
uv run $SKILL_DIR/scripts/cloud_run_revisions.py \
  --start YYYY-MM-DD --end YYYY-MM-DD \
  --all-projects

# 5. One-shot weekly report
uv run $SKILL_DIR/scripts/weekly_report.py \
  --target-start YYYY-MM-DD --target-end YYYY-MM-DD \
  --baseline-periods 2 --normalize-per-day
```

### Phase 2: Deep Dive (Based on Phase 1 Findings)

For each significant cost driver identified, run targeted analysis:

```bash
# Resource-level analysis for specific service
uv run $SKILL_DIR/scripts/top_changes.py \
  --target-start YYYY-MM-DD --target-end YYYY-MM-DD \
  --service "Cloud Logging" \
  --limit 30

# Project-specific breakdown
uv run $SKILL_DIR/scripts/cost_breakdown.py \
  --target-start YYYY-MM-DD --target-end YYYY-MM-DD \
  --by project

# Narrow analysis to one billed project inside the export
uv run $SKILL_DIR/scripts/cost_breakdown.py \
  --target-start YYYY-MM-DD --target-end YYYY-MM-DD \
  --project-filter kidstrong-at-home
```

### Phase 3: Change Correlation

Correlate cost changes with infrastructure and code changes:

```bash
# Git history for KidStrongBedrock
uv run $SKILL_DIR/scripts/git_deployments.py \
  --start YYYY-MM-DD --end YYYY-MM-DD \
  --repo /Users/lukemauldin/code/github.com/KidStrong/KidStrongBedrock \
  --show-files

# Git history for Terraform (if applicable)
uv run $SKILL_DIR/scripts/git_deployments.py \
  --start YYYY-MM-DD --end YYYY-MM-DD \
  --repo /Users/lukemauldin/code/github.com/KidStrong/tf-main-apps \
  --filter terraform
```

### Phase 4: Log Analysis (If Needed)

For observability-related cost increases (Cloud Logging, Cloud Trace), load the **gcp-log-analysis** skill:

```bash
LOG_SKILL_DIR="/Users/lukemauldin/.claude/skills/gcp-log-analysis"

# Error summary
uv run $LOG_SKILL_DIR/scripts/error_summary.py \
  --project ksu-live --days 14

# Timeline for specific service
uv run $LOG_SKILL_DIR/scripts/timeline.py \
  --project ksu-live --service <service-name> --days 14

# Top errors for a service
uv run $LOG_SKILL_DIR/scripts/top_errors.py \
  --project ksu-live --service <service-name> --days 14
```

### Phase 5: Report Generation

Compile findings into a structured report following the Output Format below.

## Output Format

Generate a comprehensive report with these sections:

### 1. Executive Summary
3-5 sentences summarizing:
- The cost change magnitude and direction
- Primary contributing factors
- Whether changes are expected, avoidable, or one-time

### 2. Cost Breakdown Table

| Service/SKU | Reference | Target | Delta | % Change |
|-------------|-----------|--------|-------|----------|
| Cloud Logging - Log Storage | $47.35 | $67.86 | +$20.50 | +43.3% |
| Cloud Trace - Spans Ingested | $30.04 | $41.87 | +$11.83 | +39.4% |
| ... | ... | ... | ... | ... |

### 3. Root Cause Analysis
For each significant cost driver:
- **What changed**: Specific resource or SKU
- **Why it increased**: Usage pattern, configuration, or traffic change
- **Evidence**: Script output, commits, deployments

### 4. Recommendations
Prioritized list with:

| Action | Est. Monthly Savings | Complexity | Risk |
|--------|---------------------|------------|------|
| Reduce log verbosity (DEBUG→INFO) | $60-80 | Low | Low |
| Implement trace sampling (50%) | $40-50 | Medium | Low |
| ... | ... | ... | ... |

### 5. Monitoring Suggestions
- Proposed alerts or dashboards
- Budget threshold recommendations

## Scripts Reference

| Script | Purpose | Key Flags |
|--------|---------|-----------|
| `cost_breakdown.py` | Compare costs by service/SKU/project across all exported projects or a filtered one | `--by`, `--project-filter`, `--bq-project`, `--baseline-periods`, `--normalize-per-day`, `--exclude-tax-adjustments` |
| `daily_costs.py` | Daily cost trends and anomalies across all exported projects or a filtered one | `--show-services`, `--service`, `--project`, `--bq-project`, `--exclude-tax-adjustments` |
| `top_changes.py` | Resource-level cost attribution across all exported projects or a filtered one | `--service`, `--project`, `--bq-project`, `--min-delta`, `--baseline-periods` |
| `cloud_run_revisions.py` | Deployment history | `--all-projects`, `--limit`, `--skip-job-executions` |
| `git_deployments.py` | Code change correlation | `--filter`, `--show-files` |
| `weekly_report.py` | One-shot Markdown report | `--project-filter`, `--bq-project`, `--baseline-periods`, `--normalize-per-day`, `--output` |

### Script Behavior Notes

#### cost_breakdown.py
- **Project scope**:
  - Defaults to **all** billed `project.id` values present in the billing export
  - Use `--project-filter <project-id>` to narrow the cost scope
  - Use `--bq-project <project-id>` only to choose where the BigQuery job runs
- **Default filtering by dimension**:
  - `--by service` and `--by sku`: Shows cost **increases** only by default (use `--show-decreases` to see all)
  - `--by project`: Shows **all** changes by default (since project costs often decrease)
  - Use `--increases-only` to force increases-only filter for project view
- If filtering removes all results, a helpful message explains how to see all changes
- **Baseline averaging**: `--baseline-periods N` averages N prior periods for reference
- **Per-day normalization**: `--normalize-per-day` divides costs by days to compare unequal ranges
- **Cost type filters**: `--exclude-tax-adjustments` or `--cost-type/--exclude-cost-type`
- Output includes **Credits Δ** to separate usage growth from credit shifts

#### daily_costs.py
- **Project scope**:
  - Defaults to **all** billed `project.id` values in the export
  - Use `--project <project-id>` to narrow the cost scope
  - Use `--bq-project <project-id>` only for BigQuery execution context
- **Billing lag detection**: Automatically warns when days appear to have incomplete data
- Days with <10% of average line items or <$1 cost are flagged as potentially incomplete
- GCP billing exports have 24-48 hour lag, so recent days should be interpreted carefully
- **Cost type filters**: `--exclude-tax-adjustments` or `--cost-type/--exclude-cost-type`

#### cloud_run_revisions.py
- **Permission handling**: Permission errors (e.g., for `kidstrong-infra`) are collected and reported at the end rather than interrupting output
- When using `--all-projects`, inaccessible projects are summarized at the end
- **Config changes**: Compares cost-relevant settings (CPU, memory, concurrency, min/max scale) vs prior revision
- **Job execution counts**: Summarizes executions in range (skip with `--skip-job-executions`)

#### weekly_report.py
- **One-shot report**: Generates a Markdown report with service/resource deltas and optional deployment/git summaries
- **Output**: `--output` defaults to `gcp-cost-report-<start>-to-<end>.md`
- **Project scope**:
  - Defaults to all exported billed projects unless `--project-filter` is set
  - Report metadata now states both billed project scope and BigQuery host project

### Date Range Handling
- **Inclusive dates**: Both start and end dates are inclusive
- Date ranges are calculated as `(end - start).days + 1`, so 2026-01-05 to 2026-01-11 = 7 days
- The reference period defaults to the same duration immediately before the target period

## BigQuery Tables

The skill queries these billing export tables in `ksu-live.tech_billing_data`.
Those tables are hosted in the `ksu-live` BigQuery project, but they contain
cost rows for multiple KidStrong GCP projects:

| Table | Use Case |
|-------|----------|
| `gcp_billing_export_v1_01F770_268BC9_B9A577` | Service and SKU-level costs |
| `gcp_billing_export_resource_v1_01F770_268BC9_B9A577` | Resource-level attribution |

See [references/billing-tables.md](references/billing-tables.md) for schema details.

## KidStrong-Specific Context

### Projects
| Project | Environment | Notes |
|---------|-------------|-------|
| `ksu-live` | Production | Primary cost center |
| `kidstrong-at-home` | Development | Lower costs expected |
| `kidstrong-infra` | Infrastructure | Shared services |
| `kidstrongtv` | KidStrongTV app | Separate product |

Unless a billing script is given `--project-filter` or `--project`, cost analysis
includes all of the exported projects above together.

### Common Cost Drivers
- **Cloud Logging**: Log storage costs scale with verbosity (DEBUG logs are expensive)
- **Cloud Trace**: Span ingestion costs scale with traffic and instrumentation
- **Cloud Run**: CPU/memory billed per request or per instance-hour
- **Firestore (via App Engine)**: Read/write operations and storage
- **Cloud SQL**: Instance hours and storage
- **Compute Engine**: VM instance hours, network egress

### Known Cost Patterns
- **Holiday periods**: Lower traffic = lower costs (baseline adjustment needed)
- **Deployment days**: Spike in logging/tracing during rollouts
- **Migration jobs**: One-time cost increases for data migrations
- **End-of-month**: Some SKUs have usage-based billing cycles

### Code Repositories
- **KidStrongBedrock**: `/Users/lukemauldin/code/github.com/KidStrong/KidStrongBedrock`
  - Rust and Go microservices
  - Cloud Run services and jobs
- **Terraform**: `/Users/lukemauldin/code/github.com/KidStrong/tf-main-apps`
  - Infrastructure definitions
  - Resource sizing changes

## Troubleshooting

### Billing Export Lag
GCP billing exports have a 24-48 hour lag. If analyzing recent data:
- The `daily_costs.py` script automatically detects and warns about incomplete days
- Days with very low line item counts (<10% of average) are flagged
- For accurate analysis, wait 48 hours after the period ends or exclude recent days
- Check `latest_export_time` in the billing table for exact export timing

### Discrepancies with GCP Console
The billing export may not include:
- Support/subscription fees
- Tax/VAT charges
- Committed use discount adjustments
- Marketplace subscriptions

If export totals don't match Console invoices, note the discrepancy and focus on relative changes.

### BigQuery Errors
If queries fail:
```bash
# Verify table access
bq show ksu-live:tech_billing_data.gcp_billing_export_v1_01F770_268BC9_B9A577

# Check authentication
gcloud auth application-default print-access-token
```

## Related Skills

- **gcp-log-analysis**: Deep dive into Cloud Logging for error patterns and log volume analysis
